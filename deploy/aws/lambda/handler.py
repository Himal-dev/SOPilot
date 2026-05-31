"""BoloBuddy production Lambda backend.

This file is intentionally dependency-light so it can be deployed as a small
Lambda zip without bundling the SOPilot development environment. It uses
ElevenLabs for real STT/alignment when configured and stores durable assessment
reports in S3 plus searchable session metadata in DynamoDB.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Attr


REPORT_BUCKET = os.environ["REPORT_BUCKET"]
DATA_STORE = os.environ.get("DATA_STORE", "s3")
SESSION_TABLE = os.environ.get("SESSION_TABLE", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
APP_TOKEN = os.environ.get("APP_TOKEN", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_STT_MODEL_ID = os.environ.get("ELEVENLABS_STT_MODEL_ID", "scribe_v2")
ELEVENLABS_USE_AUDIO_ISOLATION = os.environ.get(
    "ELEVENLABS_USE_AUDIO_ISOLATION", "false"
).lower() in {"1", "true", "yes", "on"}
RAW_AUDIO_RETENTION_DAYS = int(os.environ.get("RAW_AUDIO_RETENTION_DAYS", "30"))

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb") if DATA_STORE == "dynamodb" and SESSION_TABLE else None
table = dynamodb.Table(SESSION_TABLE) if dynamodb else None


PROMPTS = {
    "age3_4_repeat_red_ball": {
        "prompt_id": "age3_4_repeat_red_ball",
        "text": "Red ball.",
        "display_text": "Red ball.",
        "age_min": 3,
        "age_max": 4,
        "assessment_mode": "word_pronunciation",
        "language_mode": "indian_english",
        "domains": ["speech_clarity", "expressive_language", "attention"],
        "target_words": ["red", "ball"],
        "target_phonemes": ["r", "b"],
        "allowed_variants": {"red": ["laal"]},
    },
    "age3_4_name_color_bag": {
        "prompt_id": "age3_4_name_color_bag",
        "text": "What color is the school bag?",
        "display_text": "School bag ka color bolo.",
        "age_min": 3,
        "age_max": 4,
        "assessment_mode": "expressive_speaking",
        "language_mode": "hinglish",
        "domains": ["vocabulary", "expressive_language", "attention"],
        "target_words": ["bag", "red", "blue", "laal", "neela"],
        "target_phonemes": [],
        "allowed_variants": {
            "red": ["laal"],
            "blue": ["neela"],
            "bag": ["school bag"],
        },
    },
    "age3_4_follow_one_step": {
        "prompt_id": "age3_4_follow_one_step",
        "text": "Touch your bag and say bag.",
        "display_text": "Bag touch karo aur bolo: bag.",
        "age_min": 3,
        "age_max": 4,
        "assessment_mode": "expressive_speaking",
        "language_mode": "hinglish",
        "domains": ["receptive_language", "attention", "expressive_language"],
        "target_words": ["bag"],
        "target_phonemes": ["b"],
        "allowed_variants": {"bag": ["school bag"]},
    },
    "age5_6_sentence_school_bag": {
        "prompt_id": "age5_6_sentence_school_bag",
        "text": "I packed my school bag.",
        "display_text": "I packed my school bag.",
        "age_min": 5,
        "age_max": 6,
        "assessment_mode": "sentence_reading",
        "language_mode": "indian_english",
        "domains": ["speech_clarity", "working_memory", "expressive_language"],
        "target_words": ["packed", "school", "bag"],
        "target_phonemes": ["sk", "p"],
        "allowed_variants": {"school": ["iskool"]},
    },
    "age5_6_sound_robot_red": {
        "prompt_id": "age5_6_sound_robot_red",
        "text": "The robot has a red rocket.",
        "display_text": "The robot has a red rocket.",
        "age_min": 5,
        "age_max": 6,
        "assessment_mode": "phonics_practice",
        "language_mode": "indian_english",
        "domains": ["phonological_awareness", "speech_clarity", "processing_fluency"],
        "target_words": ["robot", "red", "rocket"],
        "target_phonemes": ["r"],
        "allowed_variants": {"red": ["laal"]},
    },
    "age5_6_why_raincoat": {
        "prompt_id": "age5_6_why_raincoat",
        "text": "Why do we wear a raincoat when it rains?",
        "display_text": "Raincoat kyun pehente hain?",
        "age_min": 5,
        "age_max": 6,
        "assessment_mode": "expressive_speaking",
        "language_mode": "hinglish",
        "domains": ["narrative_reasoning", "expressive_language", "vocabulary"],
        "target_words": ["raincoat", "rain", "baarish", "wet", "dry"],
        "target_phonemes": [],
        "allowed_variants": {
            "rain": ["baarish"],
            "wet": ["geela"],
            "dry": ["sukha"],
        },
    },
    "age7_8_code_switch_lunch": {
        "prompt_id": "age7_8_code_switch_lunch",
        "text": "I went to school, phir maine lunch khaya.",
        "display_text": "I went to school, phir maine lunch khaya.",
        "age_min": 7,
        "age_max": 8,
        "assessment_mode": "sentence_reading",
        "language_mode": "code_switch",
        "domains": ["code_switch_control", "working_memory", "speech_clarity"],
        "target_words": ["went", "school", "phir", "maine", "lunch", "khaya"],
        "target_phonemes": ["sk", "kh"],
        "allowed_variants": {
            "school": ["iskool"],
            "lunch": ["tiffin"],
            "phir": ["fir"],
        },
    },
    "age7_8_story_sequence_space": {
        "prompt_id": "age7_8_story_sequence_space",
        "text": "Tell me what happened first and next in a space story.",
        "display_text": "Space story mein pehle kya hua, phir kya hua?",
        "age_min": 7,
        "age_max": 8,
        "assessment_mode": "expressive_speaking",
        "language_mode": "hinglish",
        "domains": ["narrative_reasoning", "expressive_language", "processing_fluency"],
        "target_words": ["first", "next", "space", "rocket", "moon", "pehle", "phir"],
        "target_phonemes": ["sp", "r"],
        "allowed_variants": {"moon": ["chaand"], "story": ["kahani"], "next": ["phir"]},
    },
    "age7_8_memory_metro": {
        "prompt_id": "age7_8_memory_metro",
        "text": "The metro stopped, then my friend found the blue ticket.",
        "display_text": "The metro stopped, then my friend found the blue ticket.",
        "age_min": 7,
        "age_max": 8,
        "assessment_mode": "sentence_reading",
        "language_mode": "indian_english",
        "domains": ["working_memory", "processing_fluency", "speech_clarity"],
        "target_words": ["metro", "stopped", "friend", "blue", "ticket"],
        "target_phonemes": ["st", "fr", "bl"],
        "allowed_variants": {"friend": ["dost"], "blue": ["neela"]},
    },
}


BATTERIES = [
    {
        "battery_id": "bolo_age_3_4_foundation",
        "title": "Ages 3-4 Foundation Voice And Language Play",
        "age_min": 3,
        "age_max": 4,
        "prompt_ids": [
            "age3_4_repeat_red_ball",
            "age3_4_name_color_bag",
            "age3_4_follow_one_step",
        ],
        "domains": [
            "speech_clarity",
            "expressive_language",
            "receptive_language",
            "vocabulary",
            "attention",
        ],
    },
    {
        "battery_id": "bolo_age_5_6_sentence_reasoning",
        "title": "Ages 5-6 Sentence, Sound, And Simple Why",
        "age_min": 5,
        "age_max": 6,
        "prompt_ids": [
            "age5_6_sentence_school_bag",
            "age5_6_sound_robot_red",
            "age5_6_why_raincoat",
        ],
        "domains": [
            "speech_clarity",
            "expressive_language",
            "phonological_awareness",
            "working_memory",
            "narrative_reasoning",
            "vocabulary",
        ],
    },
    {
        "battery_id": "bolo_age_7_8_code_switch_story",
        "title": "Ages 7-8 Code-Switch, Story, And Memory",
        "age_min": 7,
        "age_max": 8,
        "prompt_ids": [
            "age7_8_code_switch_lunch",
            "age7_8_story_sequence_space",
            "age7_8_memory_metro",
        ],
        "domains": [
            "speech_clarity",
            "code_switch_control",
            "working_memory",
            "narrative_reasoning",
            "expressive_language",
            "processing_fluency",
        ],
    },
]


DOMAIN_LABELS = {
    "speech_clarity": "Speech clarity",
    "expressive_language": "Expressive language",
    "receptive_language": "Listening and comprehension",
    "phonological_awareness": "Sound awareness",
    "working_memory": "Auditory working memory",
    "attention": "Listening attention",
    "narrative_reasoning": "Story and reasoning",
    "vocabulary": "Vocabulary",
    "code_switch_control": "Code-switch control",
    "processing_fluency": "Processing fluency",
}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or event.get("path") or "/"

    if method == "OPTIONS":
        return _response(204, {})

    try:
        if method == "GET" and path == "/health":
            return _response(200, {"ok": True, "provider_ready": bool(ELEVENLABS_API_KEY)})
        if method == "GET" and path == "/config":
            return _response(200, _public_config())
        if method == "GET" and path == "/prompts":
            age = int((event.get("queryStringParameters") or {}).get("age_years", "5"))
            return _response(200, {"battery": _battery_for_age(age), "prompts": _prompts_for_age(age)})
        if method == "POST" and path == "/sessions":
            _require_app(event)
            return _create_session(_json_body(event))
        if method == "POST" and path.endswith("/assess"):
            _require_app(event)
            session_id = path.strip("/").split("/")[1]
            return _assess_session(session_id, _json_body(event))
        if method == "GET" and path.startswith("/sessions/"):
            _require_app(event)
            session_id = path.strip("/").split("/")[1]
            return _get_session(session_id)
        if method == "GET" and path == "/admin/sessions":
            _require_admin(event)
            return _admin_sessions(event)
        if method == "GET" and path.startswith("/admin/sessions/"):
            _require_admin(event)
            session_id = path.strip("/").split("/")[2]
            return _get_session(session_id)
        return _response(404, {"error": "not_found", "path": path})
    except PermissionError as exc:
        return _response(401, {"error": "unauthorized", "message": str(exc)})
    except ProviderConfigError as exc:
        return _response(424, {"error": "provider_config_required", "message": str(exc)})
    except ValueError as exc:
        return _response(400, {"error": "bad_request", "message": str(exc)})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        print(json.dumps({"level": "error", "kind": "elevenlabs_http", "status": exc.code, "detail": detail}))
        return _response(
            502,
            {
                "error": "voice_provider_error",
                "status": exc.code,
                "message": "The voice provider rejected the request.",
            },
        )
    except Exception as exc:  # pragma: no cover - CloudWatch diagnostic path.
        print(json.dumps({"level": "error", "kind": "unhandled", "message": str(exc)}))
        return _response(500, {"error": "internal_error", "message": "Assessment service error."})


def _create_session(body: Dict[str, Any]) -> Dict[str, Any]:
    age = int(body.get("age_years") or 5)
    if age < 3 or age > 8:
        raise ValueError("age_years must be between 3 and 8.")
    if not body.get("consent_verified"):
        raise ValueError("Parent/teacher consent is required before recording.")

    child_id = _safe_id(body.get("child_id") or f"child_{uuid.uuid4().hex[:8]}")
    session_id = f"kva_{uuid.uuid4().hex[:14]}"
    battery = _battery_for_age(age)
    prompts = _prompts_for_age(age)
    now = _now()
    item = {
        "session_id": session_id,
        "child_id": child_id,
        "age_years": age,
        "age_band": _age_band(age),
        "battery_id": battery["battery_id"],
        "selected_prompt_ids": battery["prompt_ids"],
        "status": "created",
        "created_at": now,
        "updated_at": now,
        "needs_human_review": False,
        "report_s3_key": "",
    }
    _save_session_item(item)
    _log("session_created", session_id=session_id, age_years=age, battery_id=battery["battery_id"])
    return _response(200, {"session": item, "battery": battery, "prompts": prompts})


def _assess_session(session_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    session = _load_session_item(session_id)
    age = int(session["age_years"])
    battery = _battery_for_age(age)
    task_inputs = body.get("tasks") or []
    if not task_inputs:
        raise ValueError("At least one recorded task is required.")
    if not ELEVENLABS_API_KEY:
        raise ProviderConfigError("ELEVENLABS_API_KEY is not configured for real STT/alignment.")

    by_prompt = {task.get("prompt_id"): task for task in task_inputs}
    task_results = []
    all_evidence = []

    for prompt_id in battery["prompt_ids"]:
        prompt = PROMPTS[prompt_id]
        task = by_prompt.get(prompt_id)
        if not task or not task.get("audio_base64"):
            task_results.append(_missing_task(prompt))
            continue

        audio_bytes = _decode_audio(task["audio_base64"])
        mime_type = task.get("mime_type") or "audio/webm"
        audio_key = f"sessions/{session_id}/audio/{prompt_id}.{_extension_for(mime_type)}"
        s3.put_object(
            Bucket=REPORT_BUCKET,
            Key=audio_key,
            Body=audio_bytes,
            ContentType=mime_type,
            ServerSideEncryption="AES256",
            Metadata={"retention_days": str(RAW_AUDIO_RETENTION_DAYS)},
        )

        cleaned_bytes = audio_bytes
        cleaned_key = ""
        if ELEVENLABS_USE_AUDIO_ISOLATION:
            cleaned_bytes = _elevenlabs_audio_isolation(audio_bytes, mime_type)
            cleaned_key = f"sessions/{session_id}/audio/{prompt_id}.isolated.wav"
            s3.put_object(
                Bucket=REPORT_BUCKET,
                Key=cleaned_key,
                Body=cleaned_bytes,
                ContentType="audio/wav",
                ServerSideEncryption="AES256",
            )

        stt = _elevenlabs_stt(
            cleaned_bytes,
            mime_type if not cleaned_key else "audio/wav",
            _keyterms(prompt),
            prompt["language_mode"],
        )
        alignment = _elevenlabs_forced_alignment(
            cleaned_bytes,
            mime_type if not cleaned_key else "audio/wav",
            prompt["text"],
        )
        result = _score_task(prompt, stt, alignment, audio_key, cleaned_key)
        task_results.append(result)
        all_evidence.extend(result["evidence"])

    report = _build_full_report(session, battery, task_results, all_evidence)
    report_key = f"sessions/{session_id}/reports/full_report.json"
    s3.put_object(
        Bucket=REPORT_BUCKET,
        Key=report_key,
        Body=json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )

    status = "needs_human_review" if report["human_review"]["needs_human_review"] else "completed"
    _update_session_item(
        session_id,
        {
            "status": status,
            "updated_at": _now(),
            "report_s3_key": report_key,
            "overall_score": report["scores"]["overall_score"],
            "developmental_level": report["scores"]["developmental_level"],
            "needs_human_review": report["human_review"]["needs_human_review"],
            "domains": list(report["domains"].keys()),
        },
    )
    _log("assessment_completed", session_id=session_id, status=status, report_key=report_key)
    return _response(200, {"session_id": session_id, "status": status, "report": report})


def _get_session(session_id: str) -> Dict[str, Any]:
    session = _load_session_item(session_id)
    payload = {"session": _from_ddb(session), "report": None}
    if session.get("report_s3_key"):
        obj = s3.get_object(Bucket=REPORT_BUCKET, Key=session["report_s3_key"])
        payload["report"] = json.loads(obj["Body"].read().decode("utf-8"))
    return _response(200, payload)


def _admin_sessions(event: Dict[str, Any]) -> Dict[str, Any]:
    params = event.get("queryStringParameters") or {}
    limit = min(int(params.get("limit", "50")), 100)
    sessions = _list_session_items(params.get("status"), limit)
    sessions.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return _response(200, {"sessions": sessions})


def _score_task(
    prompt: Dict[str, Any],
    stt: Dict[str, Any],
    forced_alignment: Dict[str, Any],
    audio_key: str,
    cleaned_key: str,
) -> Dict[str, Any]:
    transcript = stt.get("text", "")
    reference_tokens = _tokens(prompt["text"])
    spoken_tokens = _tokens(transcript)
    word_alignment = _align_tokens(reference_tokens, spoken_tokens, prompt["allowed_variants"])
    matched = len([item for item in word_alignment if item["status"] in {"matched", "variant"}])
    missed = [item["reference"] for item in word_alignment if item["status"] == "missed"]
    changed = [item for item in word_alignment if item["status"] == "substituted"]
    total = max(1, len(reference_tokens))
    word_accuracy = max(0.0, min(1.0, matched / total))
    completeness = max(0.0, min(1.0, (total - len(missed)) / total))
    stt_confidence = _stt_confidence(stt)
    alignment_confidence = _alignment_confidence(forced_alignment)
    fluency = _fluency_score(stt)
    target_sound = max(0.3, 1.0 - 0.12 * len(_target_issues(prompt, transcript)))
    overall = _weighted_score(prompt["assessment_mode"], word_accuracy, completeness, fluency, target_sound, stt_confidence, alignment_confidence)
    confidence = round((stt_confidence + alignment_confidence) / 2, 3)
    needs_review = confidence < 0.55 or overall < 0.42
    issues = []
    if stt_confidence < 0.55:
        issues.append("low_stt_confidence")
    if alignment_confidence < 0.55:
        issues.append("low_alignment_confidence")
    if overall < 0.42:
        issues.append("sensitive_developmental_signal")
    evidence = [
        {
            "id": _evidence_id(audio_key),
            "kind": "audio",
            "summary": f"Raw child recording stored at s3://{REPORT_BUCKET}/{audio_key}",
            "uri": f"s3://{REPORT_BUCKET}/{audio_key}",
        },
        {
            "id": _evidence_id(prompt["prompt_id"] + transcript),
            "kind": "transcript",
            "summary": f"ElevenLabs transcript: {transcript}",
            "provider": "elevenlabs",
            "confidence": stt_confidence,
        },
        {
            "id": _evidence_id(prompt["prompt_id"] + "alignment"),
            "kind": "alignment",
            "summary": "ElevenLabs forced alignment used for reference-guided timing.",
            "provider": "elevenlabs",
            "confidence": alignment_confidence,
        },
    ]
    if cleaned_key:
        evidence.append(
            {
                "id": _evidence_id(cleaned_key),
                "kind": "audio_isolation",
                "summary": f"Audio isolation output stored at s3://{REPORT_BUCKET}/{cleaned_key}",
                "uri": f"s3://{REPORT_BUCKET}/{cleaned_key}",
                "provider": "elevenlabs",
            }
        )

    return {
        "prompt_id": prompt["prompt_id"],
        "prompt_text": prompt["text"],
        "display_text": prompt["display_text"],
        "assessment_mode": prompt["assessment_mode"],
        "domains": prompt["domains"],
        "language_mode": prompt["language_mode"],
        "spoken_transcript": transcript,
        "word_alignment": word_alignment,
        "missed_words": missed,
        "changed_words": changed,
        "target_sound_issues": _target_issues(prompt, transcript),
        "scores": {
            "word_accuracy": round(word_accuracy, 3),
            "reference_completeness": round(completeness, 3),
            "fluency_score": round(fluency, 3),
            "target_sound_score": round(target_sound, 3),
            "stt_confidence": stt_confidence,
            "alignment_confidence": alignment_confidence,
            "overall_score": round(overall, 3),
            "developmental_level": _developmental_level(overall),
        },
        "status": "needs_human_review" if needs_review else "completed",
        "review_reasons": issues,
        "evidence": evidence,
        "provider": {"stt": "elevenlabs", "forced_alignment": "elevenlabs"},
    }


def _build_full_report(
    session: Dict[str, Any],
    battery: Dict[str, Any],
    task_results: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    completed = [task for task in task_results if task["status"] in {"completed", "needs_human_review"}]
    scores = _aggregate_scores(completed)
    domains = _domain_scores(completed)
    insights = _insights(domains, completed, scores["confidence_score"])
    exercises = _exercises(insights, session["age_band"])
    review_reasons = sorted({reason for task in task_results for reason in task.get("review_reasons", [])})
    needs_review = bool(review_reasons)
    missed = [word for task in task_results for word in task.get("missed_words", [])]
    child_feedback = (
        "Nice effort! Parent ya teacher details check karenge, phir practice karenge."
        if needs_review
        else "Great! Tumne practice set complete kar liya."
    )
    adult_feedback = (
        f"The child completed {len(completed)}/{len(task_results)} age-appropriate tasks. "
        f"Overall educational practice level: {scores['developmental_level']}. "
        f"Observed domains: {', '.join(domains.keys())}. "
        "This is educational evidence, not diagnosis or IQ scoring."
    )
    if missed:
        adult_feedback += f" Skipped or uncertain words included: {', '.join(missed[:6])}."

    return {
        "session_id": session["session_id"],
        "child_id": session["child_id"],
        "age_years": int(session["age_years"]),
        "age_band": session["age_band"],
        "battery_id": battery["battery_id"],
        "title": "BoloBuddy Voice Assessment Report",
        "summary": (
            f"Assessment completed across {len(task_results)} age-appropriate task(s) "
            f"for age {session['age_years']}. Use these as learning signals, not as an "
            "IQ score, diagnosis, or measure of the child's worth."
        ),
        "assessment_battery": {
            "battery_id": battery["battery_id"],
            "title": battery["title"],
            "age_years": int(session["age_years"]),
            "selected_prompt_ids": battery["prompt_ids"],
            "domains": battery["domains"],
            "age_appropriate_rationale": (
                "The battery is selected from age at session start. Ages 3-4 receive "
                "short play-like tasks; ages 7-8 receive longer code-switch, story, "
                "and memory tasks."
            ),
        },
        "task_results": task_results,
        "domains": domains,
        "insights": insights,
        "exercises": exercises,
        "scores": scores,
        "feedback": {
            "child_feedback": child_feedback,
            "adult_feedback": adult_feedback,
            "show_raw_scores_to_child": False,
        },
        "human_review": {
            "needs_human_review": needs_review,
            "review_reasons": review_reasons,
        },
        "evidence": evidence,
        "privacy": {
            "raw_audio_retention_days": RAW_AUDIO_RETENTION_DAYS,
            "provider": "elevenlabs",
            "stored_in_s3": True,
        },
        "disclaimer": (
            "This report provides educational observations from speech and language "
            "tasks. It is not an IQ test, clinical diagnosis, or measure of a child's worth."
        ),
        "created_at": _now(),
    }


def _aggregate_scores(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not tasks:
        return {
            "overall_score": 0.0,
            "word_accuracy": 0.0,
            "reference_completeness": 0.0,
            "fluency_score": 0.0,
            "confidence_score": 0.0,
            "developmental_level": "blooming",
        }
    overall = _avg(task["scores"]["overall_score"] for task in tasks)
    confidence = _avg(
        (task["scores"]["stt_confidence"] + task["scores"]["alignment_confidence"]) / 2
        for task in tasks
    )
    return {
        "overall_score": round(overall, 3),
        "word_accuracy": round(_avg(task["scores"]["word_accuracy"] for task in tasks), 3),
        "reference_completeness": round(_avg(task["scores"]["reference_completeness"] for task in tasks), 3),
        "fluency_score": round(_avg(task["scores"]["fluency_score"] for task in tasks), 3),
        "confidence_score": round(confidence, 3),
        "developmental_level": _developmental_level(overall),
    }


def _domain_scores(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    values: Dict[str, List[float]] = {}
    prompts: Dict[str, List[str]] = {}
    for task in tasks:
        for domain in task["domains"]:
            values.setdefault(domain, []).append(_domain_value(domain, task))
            prompts.setdefault(domain, []).append(task["prompt_id"])
    return {
        domain: {
            "label": DOMAIN_LABELS.get(domain, domain.replace("_", " ").title()),
            "score": round(_avg(score_values), 3),
            "level": _domain_level(_avg(score_values)),
            "prompts": prompts[domain],
            "task_count": len(prompts[domain]),
        }
        for domain, score_values in values.items()
    }


def _domain_value(domain: str, task: Dict[str, Any]) -> float:
    scores = task["scores"]
    if domain in {"speech_clarity", "phonological_awareness"}:
        return _avg([scores["target_sound_score"], scores["alignment_confidence"]])
    if domain in {"working_memory", "expressive_language", "vocabulary"}:
        return _avg([scores["word_accuracy"], scores["reference_completeness"]])
    if domain in {"attention", "processing_fluency", "narrative_reasoning"}:
        return scores["fluency_score"]
    if domain == "code_switch_control":
        return _avg([scores["word_accuracy"], scores["fluency_score"]])
    return scores["overall_score"]


def _insights(domains: Dict[str, Any], tasks: List[Dict[str, Any]], confidence: float) -> List[Dict[str, Any]]:
    insights = []
    for domain, payload in domains.items():
        score = payload["score"]
        severity = "strength" if score >= 0.78 else "review" if score < 0.45 else "practice"
        label = payload["label"]
        if severity == "strength":
            summary = f"{label} looked comfortable across the attempted task(s)."
        elif severity == "review":
            summary = f"{label} needs cautious adult review because task evidence or confidence was low."
        else:
            summary = f"{label} is a useful practice area for the next few sessions."
        insights.append(
            {
                "domain": domain,
                "label": label,
                "summary": summary,
                "severity": severity,
                "confidence": confidence,
            }
        )
    if any(task.get("missed_words") for task in tasks):
        insights.append(
            {
                "domain": "expressive_language",
                "label": "Small word completion",
                "summary": "Small function words were skipped or uncertain; practice with slow finger-tracking.",
                "severity": "practice",
                "confidence": confidence,
            }
        )
    return insights


def _exercises(insights: List[Dict[str, Any]], age_band: str) -> List[Dict[str, Any]]:
    exercises = []
    seen = set()
    for insight in insights:
        if insight["severity"] == "strength":
            continue
        activity = _exercise_for(insight["domain"], age_band)
        key = (insight["domain"], activity)
        if key in seen:
            continue
        seen.add(key)
        exercises.append(
            {
                "skill": insight["label"],
                "activity": activity,
                "priority": "high" if insight["severity"] == "review" else "medium",
                "mode": "home_practice",
            }
        )
    if not exercises:
        exercises.append(
            {
                "skill": "Confidence",
                "activity": "Repeat one favorite prompt, then try a slightly longer one.",
                "priority": "low",
                "mode": "home_practice",
            }
        )
    return exercises[:5]


def _exercise_for(domain: str, age_band: str) -> str:
    if age_band == "3-4":
        options = {
            "speech_clarity": "Play a two-word echo game: red ball, blue bag, happy robot.",
            "expressive_language": "Ask the child to name one object and one color during play.",
            "receptive_language": "Give one playful instruction: touch the bag, then say bag.",
            "attention": "Try one prompt after a clap, then celebrate the attempt.",
        }
    elif age_band == "5-6":
        options = {
            "phonological_awareness": "Pick one target sound and say three fun words slowly.",
            "expressive_language": "Use one full sentence about school, lunchbox, or a robot.",
            "working_memory": "Repeat a short sentence after hearing it once.",
            "narrative_reasoning": "Answer one small why question with because.",
        }
    else:
        options = {
            "code_switch_control": "Read one Hinglish sentence slowly, then explain it in your own words.",
            "narrative_reasoning": "Tell a three-step story: start, what changed, what happened next.",
            "working_memory": "Listen to a longer sentence and repeat it with all small words.",
            "processing_fluency": "Practice one sentence twice: first slowly, then storyteller speed.",
        }
    return options.get(domain, "Practice one short sentence slowly, then say it again with confidence.")


def _missing_task(prompt: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "prompt_id": prompt["prompt_id"],
        "prompt_text": prompt["text"],
        "display_text": prompt["display_text"],
        "assessment_mode": prompt["assessment_mode"],
        "domains": prompt["domains"],
        "language_mode": prompt["language_mode"],
        "spoken_transcript": "",
        "word_alignment": [],
        "missed_words": [],
        "changed_words": [],
        "target_sound_issues": [],
        "scores": {
            "word_accuracy": 0.0,
            "reference_completeness": 0.0,
            "fluency_score": 0.0,
            "target_sound_score": 0.0,
            "stt_confidence": 0.0,
            "alignment_confidence": 0.0,
            "overall_score": 0.0,
            "developmental_level": "blooming",
        },
        "status": "needs_human_review",
        "review_reasons": ["missing_recording"],
        "evidence": [],
        "provider": {"stt": "elevenlabs", "forced_alignment": "elevenlabs"},
    }


def _elevenlabs_stt(audio: bytes, mime_type: str, keyterms: List[str], language_mode: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "model_id": ELEVENLABS_STT_MODEL_ID,
        "timestamps_granularity": "word",
        "diarize": "false",
    }
    for term in keyterms[:1000]:
        fields.setdefault("keyterms", []).append(term)
    if language_mode == "indian_english":
        fields["language_code"] = "en"
    body, content_type = _multipart_body("file", f"audio.{_extension_for(mime_type)}", mime_type, audio, fields)
    return _post_elevenlabs_json("/v1/speech-to-text", body, content_type)


def _elevenlabs_forced_alignment(audio: bytes, mime_type: str, reference_text: str) -> Dict[str, Any]:
    body, content_type = _multipart_body(
        "file",
        f"audio.{_extension_for(mime_type)}",
        mime_type,
        audio,
        {"text": reference_text},
    )
    return _post_elevenlabs_json("/v1/forced-alignment", body, content_type)


def _elevenlabs_audio_isolation(audio: bytes, mime_type: str) -> bytes:
    body, content_type = _multipart_body(
        "audio",
        f"audio.{_extension_for(mime_type)}",
        mime_type,
        audio,
        {"file_format": "other"},
    )
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/audio-isolation",
        data=body,
        headers={"xi-api-key": ELEVENLABS_API_KEY, "content-type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:  # nosec B310
        return response.read()


def _post_elevenlabs_json(path: str, body: bytes, content_type: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        "https://api.elevenlabs.io" + path,
        data=body,
        headers={"xi-api-key": ELEVENLABS_API_KEY, "content-type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as response:  # nosec B310
        raw = response.read().decode("utf-8")
    return json.loads(raw or "{}")


def _multipart_body(
    file_field: str,
    file_name: str,
    mime_type: str,
    file_bytes: bytes,
    fields: Dict[str, Any],
) -> Tuple[bytes, str]:
    boundary = f"----bolobuddy{uuid.uuid4().hex}"
    chunks: List[bytes] = []
    for key, value in fields.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                    str(item).encode(),
                    b"\r\n",
                ]
            )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_name}"\r\n'
            ).encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _public_config() -> Dict[str, Any]:
    return {
        "app": "BoloBuddy Voice Assessment",
        "provider_ready": bool(ELEVENLABS_API_KEY),
        "data_store": DATA_STORE,
        "age_range": [3, 8],
        "supported_languages": ["Indian English", "Hindi", "Hinglish", "code-switch"],
        "admin_enabled": bool(ADMIN_TOKEN),
        "app_token_required": bool(APP_TOKEN),
    }


def _prompts_for_age(age: int) -> List[Dict[str, Any]]:
    battery = _battery_for_age(age)
    return [PROMPTS[prompt_id] for prompt_id in battery["prompt_ids"]]


def _battery_for_age(age: int) -> Dict[str, Any]:
    for battery in BATTERIES:
        if battery["age_min"] <= age <= battery["age_max"]:
            return battery
    raise ValueError("age_years must be between 3 and 8.")


def _age_band(age: int) -> str:
    if age <= 4:
        return "3-4"
    if age <= 6:
        return "5-6"
    return "7-8"


def _tokens(text: str) -> List[str]:
    return re.findall(r"[\w']+", text.lower())


def _align_tokens(reference: List[str], spoken: List[str], variants: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    alignment = []
    j = 0
    for ref in reference:
        if j >= len(spoken):
            alignment.append({"reference": ref, "spoken": None, "status": "missed"})
            continue
        candidate = spoken[j]
        allowed = {item.lower() for item in variants.get(ref, [])}
        if candidate == ref:
            alignment.append({"reference": ref, "spoken": candidate, "status": "matched"})
            j += 1
        elif candidate in allowed:
            alignment.append({"reference": ref, "spoken": candidate, "status": "variant"})
            j += 1
        elif j + 1 < len(spoken) and spoken[j + 1] == ref:
            alignment.append({"reference": None, "spoken": candidate, "status": "inserted"})
            j += 1
            alignment.append({"reference": ref, "spoken": spoken[j], "status": "matched"})
            j += 1
        else:
            alignment.append({"reference": ref, "spoken": candidate, "status": "substituted"})
            j += 1
    for extra in spoken[j:]:
        alignment.append({"reference": None, "spoken": extra, "status": "inserted"})
    return alignment


def _target_issues(prompt: Dict[str, Any], transcript: str) -> List[Dict[str, Any]]:
    issues = []
    spoken = set(_tokens(transcript))
    for word in prompt["target_words"]:
        variants = set(prompt["allowed_variants"].get(word, []))
        if word.lower() not in spoken and not (spoken & {v.lower() for v in variants}):
            issues.append(
                {
                    "issue_type": "target_sound_needs_practice",
                    "token": word,
                    "child_label": f"{word} sound",
                    "confidence": 0.58,
                }
            )
    return issues[:4]


def _weighted_score(
    mode: str,
    word_accuracy: float,
    completeness: float,
    fluency: float,
    target_sound: float,
    stt_confidence: float,
    alignment_confidence: float,
) -> float:
    confidence = (stt_confidence + alignment_confidence) / 2
    if mode == "expressive_speaking":
        return max(0.0, min(1.0, 0.25 * completeness + 0.35 * fluency + 0.2 * word_accuracy + 0.2 * confidence))
    if mode == "word_pronunciation":
        return max(0.0, min(1.0, 0.4 * target_sound + 0.3 * word_accuracy + 0.3 * confidence))
    return max(0.0, min(1.0, 0.32 * word_accuracy + 0.26 * completeness + 0.17 * target_sound + 0.15 * fluency + 0.10 * confidence))


def _stt_confidence(stt: Dict[str, Any]) -> float:
    words = stt.get("words") or []
    confidences = []
    for item in words:
        if item.get("type", "word") != "word":
            continue
        if "confidence" in item:
            confidences.append(float(item["confidence"]))
        elif "logprob" in item:
            confidences.append(max(0.0, min(1.0, 1.0 + float(item["logprob"]))))
    if confidences:
        return round(_avg(confidences), 3)
    return round(float(stt.get("language_probability", 0.65)), 3) if stt.get("text") else 0.0


def _alignment_confidence(alignment: Dict[str, Any]) -> float:
    if "loss" in alignment:
        return round(max(0.0, min(1.0, 1.0 - float(alignment["loss"]))), 3)
    words = alignment.get("words") or []
    losses = [float(item.get("loss", 0.25)) for item in words]
    return round(max(0.0, min(1.0, 1.0 - _avg(losses))), 3) if losses else 0.65


def _fluency_score(stt: Dict[str, Any]) -> float:
    words = [item for item in stt.get("words", []) if item.get("type", "word") == "word"]
    if len(words) < 2:
        return 0.72 if words else 0.0
    pauses = []
    for prev, cur in zip(words, words[1:]):
        if "end" in prev and "start" in cur:
            pauses.append(max(0.0, float(cur["start"]) - float(prev["end"])))
    long_pauses = len([pause for pause in pauses if pause > 1.2])
    return max(0.35, min(1.0, 0.92 - 0.14 * long_pauses))


def _developmental_level(score: float) -> str:
    if score < 0.45:
        return "blooming"
    if score < 0.62:
        return "practicing"
    if score < 0.76:
        return "growing"
    if score < 0.88:
        return "confident"
    return "shining"


def _domain_level(score: float) -> str:
    if score < 0.45:
        return "needs_review"
    if score < 0.62:
        return "emerging"
    if score < 0.78:
        return "developing"
    return "comfortable"


def _keyterms(prompt: Dict[str, Any]) -> List[str]:
    terms = set(prompt["target_words"])
    for key, values in prompt["allowed_variants"].items():
        terms.add(key)
        terms.update(values)
    return sorted(terms)


def _load_session_item(session_id: str) -> Dict[str, Any]:
    if table:
        result = table.get_item(Key={"session_id": session_id})
        if "Item" not in result:
            raise ValueError(f"Unknown session_id {session_id}.")
        return _from_ddb(result["Item"])
    key = _session_key(session_id)
    try:
        obj = s3.get_object(Bucket=REPORT_BUCKET, Key=key)
    except s3.exceptions.NoSuchKey as exc:
        raise ValueError(f"Unknown session_id {session_id}.") from exc
    return json.loads(obj["Body"].read().decode("utf-8"))


def _save_session_item(item: Dict[str, Any]) -> None:
    if table:
        table.put_item(Item=_to_ddb(item))
        return
    s3.put_object(
        Bucket=REPORT_BUCKET,
        Key=_session_key(item["session_id"]),
        Body=json.dumps(item, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def _update_session_item(session_id: str, updates: Dict[str, Any]) -> None:
    if table:
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression=(
                "SET #s=:s, updated_at=:u, report_s3_key=:r, overall_score=:o, "
                "developmental_level=:d, needs_human_review=:h, domains=:domains"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=_to_ddb(
                {
                    ":s": updates["status"],
                    ":u": updates["updated_at"],
                    ":r": updates["report_s3_key"],
                    ":o": updates["overall_score"],
                    ":d": updates["developmental_level"],
                    ":h": updates["needs_human_review"],
                    ":domains": updates["domains"],
                }
            ),
        )
        return
    item = _load_session_item(session_id)
    item.update(updates)
    _save_session_item(item)


def _list_session_items(status: Optional[str], limit: int) -> List[Dict[str, Any]]:
    if table:
        scan_kwargs: Dict[str, Any] = {"Limit": limit}
        if status:
            scan_kwargs["FilterExpression"] = Attr("status").eq(status)
        result = table.scan(**scan_kwargs)
        return [_from_ddb(item) for item in result.get("Items", [])]

    sessions = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=REPORT_BUCKET, Prefix="sessions/"):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not key.endswith("/session.json"):
                continue
            obj = s3.get_object(Bucket=REPORT_BUCKET, Key=key)
            session = json.loads(obj["Body"].read().decode("utf-8"))
            if status and session.get("status") != status:
                continue
            sessions.append(session)
            if len(sessions) >= limit:
                return sessions
    return sessions


def _session_key(session_id: str) -> str:
    return f"sessions/{session_id}/session.json"


def _require_admin(event: Dict[str, Any]) -> None:
    if not ADMIN_TOKEN:
        raise PermissionError("Admin dashboard token is not configured.")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = headers.get("x-admin-token") or headers.get("authorization", "").replace("Bearer ", "")
    if token != ADMIN_TOKEN:
        raise PermissionError("Admin token is required.")


def _require_app(event: Dict[str, Any]) -> None:
    if not APP_TOKEN:
        raise PermissionError("App token is not configured.")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-app-token") != APP_TOKEN:
        raise PermissionError("App token is required.")


def _json_body(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def _decode_audio(audio_base64: str) -> bytes:
    if "," in audio_base64 and audio_base64.startswith("data:"):
        audio_base64 = audio_base64.split(",", 1)[1]
    data = base64.b64decode(audio_base64)
    if not data:
        raise ValueError("Audio recording is empty.")
    return data


def _extension_for(mime_type: str) -> str:
    guessed = mimetypes.guess_extension(mime_type or "")
    if guessed:
        return guessed.lstrip(".")
    if "webm" in mime_type:
        return "webm"
    if "wav" in mime_type:
        return "wav"
    return "bin"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)[:80]


def _evidence_id(value: str) -> str:
    return "ev_" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _avg(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _log(event_type: str, **payload: Any) -> None:
    print(json.dumps({"event_type": event_type, "ts": _now(), **payload}, default=str))


def _response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
        },
        "body": json.dumps(body, default=_json_default),
    }


def _to_ddb(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(item) for item in value]
    return value


def _from_ddb(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: _from_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_ddb(item) for item in value]
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _from_ddb(value)
    return str(value)


class ProviderConfigError(RuntimeError):
    pass


handler = lambda_handler
