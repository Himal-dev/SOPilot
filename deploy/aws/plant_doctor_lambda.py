"""AWS Lambda entrypoint for the hosted Plant Doctor FastAPI app."""

from mangum import Mangum

from app.server import app


lambda_handler = Mangum(app, lifespan="off")
