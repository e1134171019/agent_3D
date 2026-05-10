# -*- coding: utf-8 -*-
"""Adapters package for the active Phase-0 decision mainline."""

from .adaptive_threshold import AdaptiveThreshold
from .historical_run_backfill import HistoricalRunBackfillRecord, backfill_record_schema
from .pytorch_decision_model import (
    DecisionOutcomeMLP,
    build_augmented_training_batch,
    build_augmented_feature_vector,
    build_backfill_augmented_feature_vector,
    build_backfill_feature_vector,
    build_feature_vector,
    build_teacher_feature_vector,
    build_training_batch,
    load_jsonl_records,
    load_feedback_records,
    predict_augmented_decision_usefulness,
    predict_decision_usefulness,
    train_augmented_decision_model,
    train_decision_model,
)
from .qwen_teacher import LocalOllamaTeacher, QwenTeacherLabel, teacher_output_schema

__all__ = [
    "AdaptiveThreshold",
    "DecisionOutcomeMLP",
    "HistoricalRunBackfillRecord",
    "LocalOllamaTeacher",
    "QwenTeacherLabel",
    "backfill_record_schema",
    "build_augmented_training_batch",
    "build_augmented_feature_vector",
    "build_backfill_augmented_feature_vector",
    "build_backfill_feature_vector",
    "build_feature_vector",
    "build_teacher_feature_vector",
    "build_training_batch",
    "load_jsonl_records",
    "load_feedback_records",
    "predict_augmented_decision_usefulness",
    "predict_decision_usefulness",
    "teacher_output_schema",
    "train_augmented_decision_model",
    "train_decision_model",
]
