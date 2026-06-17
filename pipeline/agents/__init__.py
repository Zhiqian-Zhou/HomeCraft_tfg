"""HomeCraft v2 — multi-agent pipeline.

Stages (text → voxel JSON):
    retriever      → top-K reference buildings by TF-IDF + Alexander score
    main_agent     → design_intent.json (BOT skeleton + connectors)
    room_agent     → room_plan.json (shape ops respecting connectors)
    exterior_agent → exterior_plan.json
    aggregator     → master_plan.json (BOT + ordered ops + injected connectors)
    voxelizer      → ReferenceBuilding JSON (compose + wrap)

Determinism: retriever, alexander_scorer, aggregator, voxelizer are pure Python
(no LLM). main_agent / room_agent / exterior_agent call OpenRouter via llm.py.
"""
