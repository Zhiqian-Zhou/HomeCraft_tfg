"""Skill Gym — iterative auto-improvement of the RAG-A skill catalog.

The gym builds 10 diverse buildings in parallel, evaluates them, diagnoses
weak metrics, and produces a REPORT.md that Claude (main thread) reads to
decide which skills to create/modify. Loops until min(composite) >= 0.8.

Entry point: tools.gym.runner.GymRunner
"""
