"""Minimal MLflow tracking setup for LangChain."""

import logging
import os

import mlflow


def setup_mlflow_tracking() -> None:
    # Suppress noisy MLflow / alembic / OTel logs
    for name in ("alembic", "mlflow", "opentelemetry"):
        logging.getLogger(name).setLevel(logging.ERROR)

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment("ADF-Agent")
    mlflow.langchain.autolog()
