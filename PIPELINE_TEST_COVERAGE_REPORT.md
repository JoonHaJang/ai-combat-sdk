# Pipeline Test Coverage & Quality Report

## 1. Component Inventory

### Summary

| # | File | LOC | Purpose | Testability | Current Test Coverage |
|---|------|-----|---------|-------------|----------------------|
| 1 | `tools/evaluate.py` | 372 | Unified evaluation function — runs agent vs opponents, computes win rate with Wilson CI, loss cause analysis | **Direct** | ❌ None |
| 2 | `tools/test_suite.py` | 411 | Structural validation of BT agent YAML — checks node names, params, custom node imports, collision detection | **Direct** | ❌ None |
| 3 | `tools/adaptive_optimizer.py` | 732 | CMA-ES full-space optimizer for BT agent parameters and structure (action slots, condition params, branch on/off) | **Indirect** | ❌ None |
| 4 | `tools/generate_opponent_pool.py` | 634 | Generates ~700 orthogonal opponent BTs across 6 layers (pure, gated, phase-decomposed, param sweep, cross, counter) | **Direct** | ❌ None |
| 5 | `tools/metadata_logger.py` | 150 | Per-step CSV + sidecar JSON logger for match metadata collection (observations, actions, BT nodes) | **Direct** | ❌ None |
| 6 | `tools/analyze_metadata.py` | 837 | Quantitative analysis of CSV metadata — SAE, TIR, WPP, WCS, EIP, EVW modules | **Direct** | ❌ None |
| 7 | `tools/collect_phase1.py` | 560 | Large-scale metadata collection orchestrator — batch match execution with probe agents, coverage analysis | **Indirect** | ❌ None |
| 8 | `tools/bt_optimizer.py` | 1263 | BT Optimizer v2 — LHS search + local refinement, hierarchical scoring, parameter correlation analysis | **Indirect** | ❌ None |
| 9 | `tools/bt_optimizer_v3.py` | 541 | BT Optimizer v3 — CMA-ES + deterministic 1-round eval, discrete→continuous encoding, CSV metadata collection | **Indirect** | ❌ None |
| 10 | `tools/test_agent.py` | 115 | CLI tool for local agent testing — runs agent vs opponent for N rounds, prints W/L summary | **Direct** | ❌ None |
| 11 | `tools/opponent_classifier.py` | 351 | Infers opponent BT branch from observation dict — geometric classification (hard deck, gun attack, defensive, offensive, neutral) | **Direct** | ❌ None |
| 12 | `tools/counter_strategy_builder.py` | 309 | Analyzes StepLogger CSVs to build empirical counter-strategy table per opponent mode | **Direct** | ❌ None |
| 13 | `tools/collect_gun.py` | 87 | GUN_ATTACK data collection script — runs gun probe agents vs all opponents in parallel | **Indirect** | ❌ None |
| 14 | `tools/distill_lag_dt.py` | 267 | Decision tree distillation of LAG RL policy — extracts interpretable tactical rules from policy table | **Direct** | ❌ None |
| 15 | `tools/expand_archetypes.py` | 586 | Generates 168 BT archetypes for Prototypical Network meta-learning class balance | **Direct** | ❌ None |
| 16 | `tools/generate_agents.py` | 251 | Hypothesis-driven agent generator — creates agents with specific tactical profiles for coverage gaps | **Direct** | ❌ None |
| 17 | `tools/query_lag_policy.py` | 442 | Queries LAG RL baseline model on (AO, TA, R) grid to extract optimal action patterns | **Indirect** | ❌ None |
| 18 | `tools/validate_agent.py` | 105 | Pre-submission YAML validator — checks agent structure, custom nodes, prints stats | **Direct** | ❌ None |
| 19 | `tools/test_dogfight2_connection.py` | 110 | Interactive connection test for Dogfight 2 visualization client | **Config** | ❌ None |
| 20 | `tools/test_intent_live.py` | 57 | Live EIM (Enemy Intent Model) verification — monkey-patches shared_state to capture predictions | **Config** | ❌ None |
| 21 | `tools/train_intent_model.py` | 426 | EIM training pipeline — CSV→window extraction→ProtoNet meta-learning→model export | **Indirect** | ❌ None |

**Total: 21 files, 8,606 LOC, 0% test coverage**

---

### Detailed Inventory

#### 1. `tools/evaluate.py` (372 LOC) — **Testability: Direct**

**Purpose:** Unified evaluation entry point for all assessment tools. Runs agent vs opponent pool, computes win rates with Wilson confidence intervals, and classifies loss causes.

**Key Functions:**
- `_resolve_agent(name)` — Resolves agent name to YAML file path (submissions/, examples/)
- `_run_single(agent_path, opponent_path, ...)` — Executes single match via `BehaviorTreeMatch`
- `_wilson_ci(wins, total, z)` — Wilson score confidence interval calculation
- `evaluate(agent, opponents, rounds, ...)` — Main evaluation orchestrator returning win_rate, CI, per-opponent stats, loss causes

**Assertions/Error Handling:** FileNotFoundError for missing agents; try/except around match execution returning error dict; graceful skip for missing opponents.

**Testable Units:** `_resolve_agent` (path resolution logic), `_wilson_ci` (pure math), `evaluate` result structure (needs sim environment).

---

#### 2. `tools/test_suite.py` (411 LOC) — **Testability: Direct**

**Purpose:** Automated structural validation of BT agents before match execution. Checks YAML structure, node name collisions, custom node availability, and parameter correctness.

**Key Functions:**
- `_resolve_agent(name)` — Agent path resolution
- `_extract_node_names(tree_node)` — Recursive node name extraction from YAML tree
- `_extract_leaf_node_names(tree_node)` — Extracts Action/Condition nodes only
- `_extract_custom_node_names(tree_node)` — Filters non-builtin nodes
- `_load_init_imports(agent_dir)` — Scans nodes/ package for imported class names
- `_load_init_params(agent_dir, class_name)` — Extracts __init__ params via inspect or text parsing

**Assertions/Error Handling:** Validates against `BUILTIN_CONDITIONS` and `BUILTIN_ACTIONS` sets. Uses importlib with fallback to text parsing.

**Testable Units:** All extraction functions are pure and highly testable with synthetic YAML dicts. No simulation dependency for core logic.

---

#### 3. `tools/adaptive_optimizer.py` (732 LOC) — **Testability: Indirect**

**Purpose:** CMA-ES full-space optimizer that simultaneously searches BT node selection (which nodes to use) and node parameters. Auto-discovers `TUNABLE_PARAMS` from custom node classes.

**Key Functions:**
- `_discover_tunable_classes()` — Auto-discovers classes with TUNABLE_PARAMS in adaptive_eagle/nodes/
- `_build_param_defs()` — Constructs full parameter space (structure + node params)
- `vector_to_params(x)` — Maps [0,1]^N vector to named parameter dict
- `params_to_vector(params)` — Inverse mapping
- `_stratified_sample_opponents(k, seed)` — Stratified sampling from opponent pool manifest

**Assertions/Error Handling:** `np.clip` on vector values; try/except on module import; manifest existence fallback.

**Testable Units:** `vector_to_params`/`params_to_vector` (pure transforms), `_stratified_sample_opponents` (needs manifest file). Core optimization loop requires full sim environment.

---

#### 4. `tools/generate_opponent_pool.py` (634 LOC) — **Testability: Direct**

**Purpose:** Generates ~700 systematically designed opponent BTs across 6 layers using orthogonal tactical axes (phase focus, range, energy, aggression, action, altitude).

**Key Functions:**
- `_sel()`, `_seq()`, `_cond()`, `_act()` — BT YAML builder primitives
- `_hard_deck()` — Common hard deck avoidance subtree
- `_wrap_yaml()` — Wraps tree in standard YAML envelope
- `gen_layer1_pure()` — 90 single-action BTs
- `gen_layer2_gated()` — 240 condition-gated 2-branch BTs
- `gen_layer3_phase()` — 120 phase-decomposed 3-branch BTs

**Assertions/Error Handling:** Minimal — relies on YAML structure correctness. File I/O with `mkdir(parents=True)`.

**Testable Units:** All `gen_layer*` functions return pure data structures. Builder primitives are trivially testable. No sim dependency.

---

#### 5. `tools/metadata_logger.py` (150 LOC) — **Testability: Direct**

**Purpose:** Creates step-level callback logger for match metadata collection. Outputs CSV with 30+ observation fields and sidecar JSON with match results.

**Key Functions:**
- `create_metadata_logger(log_file, ...)` — Factory returning `(step_callback, finalize)` tuple

**Assertions/Error Handling:** Silent exception swallowing in step_callback (configurable). `mkdir(parents=True)` for output dirs.

**Testable Units:** CSV header format, step_callback field serialization (angle scaling), finalize JSON output. Can test with mock data — no sim dependency.

---

#### 6. `tools/analyze_metadata.py` (837 LOC) — **Testability: Direct**

**Purpose:** Quantitative analysis of collected CSV metadata producing 6 analysis modules (SAE, TIR, WPP, WCS, EIP, EVW).

**Key Functions:**
- `load_metadata(meta_dir)` — Loads CSV + result JSON files
- `classify_unknown_sub(ata_deg, closure_kts)` — Sub-classifies UNKNOWN BFM states
- `compute_sae(matches, lookahead)` — State-Action Effectiveness calculation
- `compute_tir(matches)` — Transition Induction Rate
- `compute_wpp(matches, k)` — WEZ Precursor Pattern extraction
- `compute_wcs(matches)` — Win Contribution Score
- `compute_eip(matches)` — Enemy Intent Profile
- `compute_evw(matches)` — Enemy Vulnerability Window

**Assertions/Error Handling:** `safe_float()` helper for robust numeric parsing. Empty-data guards throughout.

**Testable Units:** All compute_* functions accept list-of-dicts — fully testable with synthetic match data. `classify_unknown_sub` is pure logic.

---

#### 7. `tools/collect_phase1.py` (560 LOC) — **Testability: Indirect**

**Purpose:** Orchestrates large-scale metadata collection across all agent pairs with parallel execution support and coverage analysis.

**Key Functions:**
- `build_match_list(base_agents, probe_agents)` — Generates all agent pair combinations
- `run_single_match(args)` — Worker function for single match execution
- `run_batch(batch_args)` — Batch worker for spawn overhead minimization
- `analyze_coverage(output_dir)` — Post-collection coverage statistics
- `load_archetype_agents()` — Loads archetype agent names from manifest

**Assertions/Error Handling:** try/except in workers returning error tuples. Manifest existence check.

**Testable Units:** `build_match_list` (pure combinatorics), `load_archetype_agents` (file I/O). Match execution requires sim.

---

#### 8. `tools/bt_optimizer.py` (1263 LOC) — **Testability: Indirect**

**Purpose:** BT Optimizer v2 with LHS exploration + local perturbation refinement. Includes parameter correlation analysis (Spearman ρ) and tournament validation.

**Key Functions:**
- `_spearman(x, y)` — Pure Python Spearman rank correlation
- `print_param_analysis(explore_results)` — Parameter sensitivity report
- PARAM_SPACE definition — 21-dimensional search space
- Scoring constants: `WIN_BASE`, `DRAW_BASE`, `LOSS_BASE`, `HP_WEIGHT`

**Assertions/Error Handling:** Guard for insufficient results (<10). Scoring hierarchy guarantees documented in comments.

**Testable Units:** `_spearman` (pure math), scoring formula (pure), parameter space validation. Core loop requires sim.

---

#### 9. `tools/bt_optimizer_v3.py` (541 LOC) — **Testability: Indirect**

**Purpose:** CMA-ES optimizer with deterministic 1-round evaluation and continuous encoding of discrete parameters.

**Key Functions:** Similar structure to bt_optimizer.py but with CMA-ES instead of LHS.

**Testable Units:** Vector encoding/decoding, BT YAML generation function.

---

#### 10. `tools/test_agent.py` (115 LOC) — **Testability: Direct**

**Purpose:** Simple CLI for running agent vs opponent matches with win/loss reporting.

**Key Functions:**
- `get_agent_path(name)` — Agent file path resolution (submissions → examples → direct path)
- `main()` — CLI entry point

**Assertions/Error Handling:** FileNotFoundError with descriptive message. Platform-independent path handling.

**Testable Units:** `get_agent_path` (path resolution logic — needs filesystem fixtures).

---

#### 11. `tools/opponent_classifier.py` (351 LOC) — **Testability: Direct**

**Purpose:** Geometric classifier that infers opponent's current BT branch from our observation dict. Returns mode, confidence, likely action, and counter-strategy.

**Key Functions:**
- `classify_opponent(obs, opponent_type)` — Main classifier using aa_deg, ata_deg, distance, tc_type thresholds
- `OpponentMode` — Constants class (HARD_DECK, GUN_ATTACK, DEFENSIVE, OFFENSIVE, NEUTRAL_1C, NEUTRAL_2C)

**Assertions/Error Handling:** Graceful defaults for missing obs keys via `.get()`.

**Testable Units:** Fully testable with synthetic obs dicts. No sim dependency. Pure threshold logic.

---

#### 12. `tools/counter_strategy_builder.py` (309 LOC) — **Testability: Direct**

**Purpose:** Analyzes StepLogger CSV files to build empirical mode distribution and counter-strategy recommendations.

**Key Functions:**
- `analyze_log_file(log_path, opponent_type)` — Single CSV analysis → mode counts + transitions
- `analyze_directory(log_dir, opponent_type)` — Aggregate over directory
- `print_counter_table()` — Static counter-strategy reference
- `COUNTER_TABLE` — Predefined counter-strategy dict

**Assertions/Error Handling:** try/except on float parsing. Empty file checks.

**Testable Units:** `analyze_log_file` with synthetic CSV, `COUNTER_TABLE` structure validation. No sim dependency.

---

#### 13. `tools/collect_gun.py` (87 LOC) — **Testability: Indirect**

**Purpose:** Focused GUN_ATTACK data collection using gun probe agents with parallel batch execution.

**Key Functions:**
- `run_one(args)` — Single match worker
- `run_batch(batch)` — Batch worker
- `main()` — Orchestrator with progress reporting

**Testable Units:** Pair generation logic only. Match execution requires sim.

---

#### 14. `tools/distill_lag_dt.py` (267 LOC) — **Testability: Direct**

**Purpose:** Distills LAG RL policy into decision tree rules for BT node consumption.

**Key Functions:** Tactical cluster mapping, sklearn DT training, rule extraction to JSON.

**Testable Units:** Cluster mapping logic, rule serialization format. DT training needs input data file.

---

#### 15. `tools/expand_archetypes.py` (586 LOC) — **Testability: Direct**

**Purpose:** Generates 168 BT archetypes across 6 intent classes for ProtoNet meta-learning.

**Key Functions:** Template-based BT generation per class (GUN_ATTACK, PURSUIT, DEFENSIVE, ENERGY, NEUTRAL, SCISSORS).

**Testable Units:** Template generation functions produce pure data. Manifest output format.

---

#### 16. `tools/generate_agents.py` (251 LOC) — **Testability: Direct**

**Purpose:** Creates hypothesis-driven agents from predefined tactical profiles using bt_optimizer_v3's BT generator.

**Key Functions:** `AGENT_PROFILES` dict → YAML generation via `generate_bt_yaml`.

**Testable Units:** Profile definitions, generated YAML structure validation.

---

#### 17. `tools/query_lag_policy.py` (442 LOC) — **Testability: Indirect**

**Purpose:** Queries LAG RL model on observation grid to extract tactical patterns.

**Key Functions:** Model loading, grid generation, action query, summary output.

**Testable Units:** Grid generation (pure math). Model query requires PyTorch model file.

---

#### 18. `tools/validate_agent.py` (105 LOC) — **Testability: Direct**

**Purpose:** Pre-submission YAML validation wrapper around `SubmissionValidator`.

**Key Functions:** `main()` — CLI with multi-path agent resolution and validation.

**Testable Units:** Path resolution logic. Validation delegates to `SubmissionValidator`.

---

#### 19. `tools/test_dogfight2_connection.py` (110 LOC) — **Testability: Config**

**Purpose:** Interactive connection test for Dogfight 2 visualization client.

**Key Functions:** `test_connection()` — Interactive (requires user input + running server).

**Testable Units:** None without mocking — interactive I/O + external service dependency.

---

#### 20. `tools/test_intent_live.py` (57 LOC) — **Testability: Config**

**Purpose:** Live EIM verification script — monkey-patches shared_state to capture intent predictions during a match.

**Key Functions:** Inline script — patches `shared_state.set_intent`, runs match, prints confidence distribution.

**Testable Units:** None standalone — tightly coupled to match execution and shared_state module.

---

#### 21. `tools/train_intent_model.py` (426 LOC) — **Testability: Indirect**

**Purpose:** Full EIM training pipeline — data loading, window extraction, ProtoNet meta-learning, model export.

**Key Functions:** CSV→episode conversion, NODE_TO_INTENT mapping, ProtoNet training loop.

**Testable Units:** Label mapping logic, window extraction. Training requires data files + PyTorch.

---

---

## 2. Source Component Inventory (`src/`)

### Summary

The `src/` directory contains the core SDK runtime: match execution, behavior tree engine, intent recognition, simulation environment, and supporting modules. Most core modules are compiled `.pyd` (Cython) binaries — only `src/match/`, `src/intent/`, and select other modules have testable Python source.

#### src/match/ — Match Execution

| # | File | LOC | Type | Testability | Public API |
|---|------|-----|------|-------------|------------|
| 1 | `runner.py` | 569 | Python | **Direct** (via `BehaviorTreeMatch`) | `BehaviorTreeMatch(tree1_file, tree2_file, ...).run()` — public match interface with CSV logging, step_callback, visualization hooks |
| 2 | `runner_core.py` | 432 | Python (compiled to .pyd for distribution) | **Indirect** | `MatchCore` — core match loop, env init, step execution. Imported by runner.py; depends on full sim stack |
| 3 | `result.cp314-win_amd64.pyd` | — | Compiled | **Indirect** | `MatchResult` — match result data class (exported via `__init__.py`) |
| 4 | `judge.cp314-win_amd64.pyd` | — | Compiled | **Indirect** | `MatchJudge`, `VictoryCondition` — win/loss/draw adjudication |
| 5 | `wez_engine.cp314-win_amd64.pyd` | — | Compiled | **Indirect** | `calculate_wez_damage` — Weapon Engagement Zone damage calculation |

#### src/intent/ — Enemy Intent Recognition

| # | File | LOC | Type | Testability | Public API |
|---|------|-----|------|-------------|------------|
| 1 | `encoder.py` | 163 | Python | **Direct** | `TacticalEncoder` (GRU+Attention, 28-dim→64-dim embedding), `obs_dict_to_tensor()`, `window_to_tensor()`, `OBS_DIM=28` |
| 2 | `proto_net.py` | 340 | Python | **Direct** | `ProtoNet` (Prototypical Network architecture), `EpisodeDataset` (N-way K-shot sampling), `INTENT_CLASSES` (6 classes), `node_to_intent()`, `predict()`, `build_prototypes()` |
| 3 | `online_tracker.py` | 261 | Python | **Direct** | `OnlineIntentTracker` (sliding window real-time inference), `.update(obs)`, `.current_intent()`, `.is_intent(str)`, `.confidence(str)`, `.from_file(path)`, `.update_prototypes_from_match()` |
| 4 | `shared_state.py` | 51 | Python | **Direct** | `register_agents()`, `set_intent()`, `get_enemy_intent()`, `get_intent()`, `clear()` — global dict-based intent sharing between runner and BT nodes |
| 5 | `bt_nodes.py` | 147 | Python | **Direct** | `EnemyIntentIs`, `EnemyIntentConfidence`, `EnemyIntentNot` — py_trees BT condition nodes reading from shared_state |

#### src/behavior_tree/ — BT Engine

| # | File | Type | Testability | Public API |
|---|------|------|-------------|------------|
| 1 | `loader.cp314-win_amd64.pyd` | Compiled | **Indirect** | `load_behavior_tree()` — YAML→py_trees tree loader |
| 2 | `task.cp314-win_amd64.pyd` | Compiled | **Indirect** | `BehaviorTreeTask` — BT execution wrapper for sim environment |
| 3 | `nodes/actions.cp314-win_amd64.pyd` | Compiled | **Indirect** | Built-in action nodes (altitude, heading, velocity control) |
| 4 | `nodes/conditions.cp314-win_amd64.pyd` | Compiled | **Indirect** | Built-in condition nodes (BFM checks, geometry checks) |

#### src/control/ — Flight Control (All Compiled)

| # | File | Type | Public API |
|---|------|------|------------|
| 1 | `combat_geometry.cp314-win_amd64.pyd` | Compiled | `CombatGeometry` — ATA, AA, HCA, range calculations |
| 2 | `bfm_classifier.cp314-win_amd64.pyd` | Compiled | BFM situation classification (OBFM/DBFM/HABFM/UNKNOWN) |
| 3 | `health_manager.cp314-win_amd64.pyd` | Compiled | `HealthGauge` — damage/health tracking |

#### src/simulation/ — JSBSim Environment (All Compiled)

All `.pyd` compiled. Contains: environment wrappers, PPO/MAPPO RL algorithms, reward functions, termination conditions, rendering, task definitions. **Not directly testable** — serves as the simulation backend for `runner_core.py`.

#### src/visualization/ — Visualization Clients (Python Source)

| # | File | LOC | Testability |
|---|------|-----|-------------|
| 1 | `cesium_ws_server.py` | — | Config (WebSocket server) |
| 2 | `dogfight2_client.py` | — | Config (TCP client) |
| 3 | `flightgear_vis.py` | — | Config (UDP client) |
| 4 | `match_visualizer.py` | — | Config (orchestrator) |
| 5 | `socket_lib.py` | — | Config (socket utilities) |

### src/ Testability Boundary Analysis

**Directly Testable Python Source (5 modules, ~1,162 LOC):**
- `src/intent/encoder.py` — Pure PyTorch, 28-dim feature encoding. Test with synthetic obs dicts.
- `src/intent/proto_net.py` — ProtoNet architecture + episode sampling. Test with synthetic tensors.
- `src/intent/online_tracker.py` — Streaming inference. Test with mock ProtoNet + synthetic obs sequences.
- `src/intent/shared_state.py` — Pure dict API. Trivially testable with no dependencies.
- `src/intent/bt_nodes.py` — py_trees conditions. Test with mock blackboard + shared_state.

**Indirectly Testable via Public API (1 module):**
- `src/match/runner.py` — `BehaviorTreeMatch` is the main integration point. Requires full sim environment (JSBSim + compiled .pyd chain). All tools/ modules that run matches go through this API.

**Compiled .pyd Boundary (not independently testable):**
- `src/match/runner_core.py` → compiled as `runner_core.pyd` for distribution
- `src/match/judge.pyd`, `result.pyd`, `wez_engine.pyd`
- `src/behavior_tree/loader.pyd`, `task.pyd`, `nodes/actions.pyd`, `nodes/conditions.pyd`
- `src/control/*` (3 modules)
- `src/simulation/**/*` (~30+ compiled modules)

---

### Testability Classification Summary

| Classification | Count | Files |
|---------------|-------|-------|
| **Direct** (pure logic, testable with mocks/synthetic data) | 17 | tools/: evaluate, test_suite, generate_opponent_pool, metadata_logger, analyze_metadata, test_agent, opponent_classifier, counter_strategy_builder, distill_lag_dt, expand_archetypes, generate_agents, validate_agent; src/intent/: encoder, proto_net, online_tracker, shared_state, bt_nodes |
| **Indirect** (requires sim environment, external models, or large data) | 8 | tools/: adaptive_optimizer, collect_phase1, bt_optimizer, bt_optimizer_v3, collect_gun, query_lag_policy, train_intent_model; src/match/: runner (via BehaviorTreeMatch) |
| **Compiled .pyd** (binary, indirect testing only) | 30+ | src/match/: runner_core, judge, result, wez_engine; src/behavior_tree/: loader, task, nodes/*; src/control/*; src/simulation/**/* |
| **Config** (interactive/external service dependency) | 7 | tools/: test_dogfight2_connection, test_intent_live; src/visualization/: cesium_ws_server, dogfight2_client, flightgear_vis, match_visualizer, socket_lib |

### Configuration & Supporting Files Inventory

| # | File | Type | Size | Purpose | Schema-Validatable? |
|---|------|------|------|---------|---------------------|
| 1 | `config/match_config.yaml` | YAML | 34 lines | Default match settings — rounds, scenario selection, output formatting, path defaults | **Yes** — flat key-value with typed fields (int, bool, string, list); straightforward JSON Schema or pydantic model |
| 2 | `config/wez_params.yaml` | YAML | 18 lines | Gun WEZ weapon parameters — angle/range limits, DPS, hard deck altitude and penalty | **Yes** — numeric-typed fields with physical unit constraints; ideal for range-validated schema |
| 3 | `config/match_rules.yaml` | YAML | 34 lines | Match rules — max steps, health, victory conditions, initial conditions (separation, altitude, speed, heading) | **Yes** — structured with nested typed fields; victory_conditions array is enum-validatable |
| 4 | `config/tournament_config.yaml` | YAML | 61 lines | Tournament system — Elo settings, round types, leaderboard display, message templates | **Yes** — mixed structure with typed numerics (k_factor, initial_rating) and template strings |
| 5 | `examples/opponent_pool/manifest.json` | JSON | ~80K tokens | Opponent pool manifest — 695 opponents across 6 layers with per-opponent metadata | **Yes** — JSON with clear structure: version, total_opponents, layers dict, opponents array; highly schema-validatable |
| 6 | `examples/adaptive_eagle/adaptive_eagle.yaml` | YAML | 117 lines | Reference BT agent — phase 4+3a v5.1 with 7 tactical branches, custom nodes | **Yes** — follows BT agent schema (name, version, description, tree with typed nodes/params) |
| 7 | `examples/adaptive_eagle/_best_opt.yaml` | YAML | — | Optimizer output — best parameter set from CMA-ES optimization | **Partial** — follows BT agent schema but optimizer-generated; structure matches agent schema |
| 8 | `examples/adaptive_eagle/_best_pool_v1.yaml` | YAML | — | Pool optimizer output — best agent from pool-based optimization | **Partial** — same as above |
| 9 | `examples/adaptive_eagle/gs_Accelerate_LeadPursuit_5000_60.yaml` | YAML | — | Grid search output — specific parameter combination result | **Partial** — follows BT agent schema |
| 10 | `examples/adaptive_eagle/test_hob.yaml` | YAML | — | Test agent — HeadOnBreak test configuration | **Partial** — follows BT agent schema |
| 11 | `examples/adaptive_eagle/nodes/__init__.py` | Python | 31 lines | Custom node package — imports 22 actions + 12 conditions + 1 EIM node | **Documentation-only** — import manifest; no config to validate |
| 12 | `examples/adaptive_eagle/nodes/custom_actions.py` | Python | 761 lines | 22 custom BFM action nodes (pursuit, energy, defensive, engagement, escape) | **Documentation-only** — Python source; testable as code, not as config |
| 13 | `examples/adaptive_eagle/nodes/custom_conditions.py` | Python | 298 lines | 12 custom condition nodes (geometry, energy, combat, orbit detection, EIM) | **Documentation-only** — Python source; testable as code, not as config |

#### Schema Validation Assessment

**Schema-Validatable (6 files):** All 4 YAML configs + opponent pool manifest + reference agent YAML have well-defined structures suitable for JSON Schema or pydantic validation. These represent the highest-priority targets for automated validation tests:

- **Config files** (`config/*.yaml`): Define numeric ranges, enum values, and required keys — a JSON Schema can enforce type correctness, required fields, and value constraints (e.g., `max_steps > 0`, `k_factor > 0`).
- **Opponent manifest** (`manifest.json`): Array-of-objects structure with consistent fields per opponent — ideal for schema validation ensuring layer consistency and opponent count integrity.
- **Agent YAML schema**: The BT agent format (name, version, tree with recursive node structure) is shared across all agent YAMLs and could be validated with a recursive JSON Schema.

**Partially Validatable (4 files):** Optimizer/grid-search output YAMLs follow the BT agent schema but may contain optimizer-specific metadata. Same schema applies with optional additional fields.

**Documentation-Only (3 files):** Python source files in `nodes/` — not configuration, but testable as Python modules (import verification, class interface checks, TUNABLE_PARAMS presence).

---

### Current Test Coverage Status

**No dedicated test files exist for any tools/ or src/ module.** There is no `tests/` directory in the project root. The only test-like files are `tools/test_suite.py` (a validation tool, not a unit test), `tools/test_agent.py` (a CLI runner, not a unit test), and `tools/test_intent_live.py` (a live verification script). The 5 testable `src/intent/` modules (1,162 LOC) represent the highest-value untested Python source in the SDK core.

---

## 3. test_suite.py Effectiveness Analysis

### Overview

`tools/test_suite.py` is the **only automated validation tool** in the pipeline. It performs 5 structural checks on BT agent YAML files before match execution. This section evaluates each check's detection capability against the 5 known bugs documented in `PIPELINE_AUDIT.md`, and assesses CI integration readiness.

### Per-Check Analysis

| # | Check Name | What It Validates | Detection Scope | Limitations |
|---|------------|-------------------|-----------------|-------------|
| 1 | `name_collision` | Custom node names don't collide with `BUILTIN_NODES` (61 builtin conditions + actions). Checks both YAML-referenced and `__init__.py`-imported names. | **Structural** — prevents silent node override where pyd builtin takes precedence over custom class. | Only checks name-level collision. Cannot detect semantic conflicts (e.g., same name used with different intent across agents). Hardcoded builtin set may drift from actual pyd contents. |
| 2 | `yaml_init_match` | YAML `params:` keys match custom node `__init__` parameter names. Uses `importlib`+`inspect` with text-parsing fallback. | **Interface** — catches typos in YAML param keys that would be silently ignored at runtime. | Only checks custom nodes with params in YAML. Skips nodes without params. `_load_init_params` hardcodes `examples.adaptive_eagle.nodes` module path — **breaks for any agent not in that directory**. |
| 3 | `init_imports` | Custom nodes referenced in YAML are imported in `nodes/__init__.py`. | **Wiring** — ensures custom node classes are discoverable by the BT loader. Missing imports cause silent fallback to builtin or load failure. | Text-based import scanning (`_load_init_imports`) may miss dynamic imports or `__all__` patterns. Does not verify the imported class actually implements the correct interface. |
| 4 | `dead_code` | Classes imported in `nodes/__init__.py` but never referenced in the YAML tree. | **Hygiene** — identifies unused imports that indicate disconnected functionality (e.g., EIM nodes imported but not used in BT). | Compares against `_extract_node_names` (all names including Sequence/Selector names), not just leaf nodes. `BaseAction` is explicitly excluded but other utility base classes would false-positive. |
| 5 | `tree_structure` | Root node is `Selector` type; first branch contains `BelowHardDeck` condition. | **Safety** — ensures hard deck avoidance is the highest-priority branch to prevent altitude-related losses. | Only checks first branch's immediate children for `BelowHardDeck`. Doesn't validate deeper nesting. Name-based check (`"HardDeck" in first_name`) is fragile. No validation of tree depth, branch count, or other structural properties. |

### Bug Detection Matrix

This matrix maps each `PIPELINE_AUDIT.md` bug against the 5 test_suite.py checks, indicating whether each check **would detect** (✅), **would not detect** (❌), or **partially relates to** (⚠️) the bug.

| Bug | Description | Severity | `name_collision` | `yaml_init_match` | `init_imports` | `dead_code` | `tree_structure` |
|-----|-------------|----------|-------------------|--------------------|----------------|-------------|------------------|
| **BUG-1** | Angle unit mismatch (radians vs degrees) between training CSV and runtime inference | CRITICAL | ❌ | ❌ | ❌ | ❌ | ❌ |
| **BUG-2** | EIM nodes not connected in adaptive_eagle YAML (intent prediction unused) | CRITICAL | ❌ | ❌ | ❌ | ✅ **Detected** | ❌ |
| **BUG-3** | Dead BFM sub-classification features in encoder (3/7 always zero) | WARNING | ❌ | ❌ | ❌ | ❌ | ❌ |
| **BUG-4** | SAE/TIR/WCS data from wrong agent matchups (eagle1 data applied to eagle2 problem) | CRITICAL | ❌ | ❌ | ❌ | ❌ | ❌ |
| **BUG-5** | Accelerate intent label conflict (PURSUIT vs NEUTRAL_CIRCLE escape) | WARNING | ❌ | ❌ | ❌ | ❌ | ❌ |

#### Detection Analysis

**BUG-1 (Angle Unit Mismatch):** No structural check can detect this. It is a **semantic/numerical bug** in `runner.py` line 348 where `obs2` (radians) is passed to `obs_dict_to_tensor` expecting degrees. Requires runtime value-range assertions or cross-module contract tests.

**BUG-2 (EIM Disconnected):** The `dead_code` check **directly detects this**. `nodes/__init__.py` imports `EnemyIntentIs`, `EnemyIntentConfidence`, `EnemyIntentNot` but the YAML tree never references them → `dead_code` reports these as unused imports. However, the check frames this as a hygiene issue (FAIL message: "import되었으나 YAML 미사용"), not as a critical architectural disconnection. The severity is understated.

**BUG-3 (Dead BFM Features):** This is an `encoder.py` data schema issue — 3 of 7 `BFM_CLASSES` one-hot dimensions are always zero. No structural YAML check can detect feature-level data quality issues. Requires feature variance analysis or data profiling tests.

**BUG-4 (Wrong Agent Data):** This is a **pipeline provenance bug** — analysis results from eagle1-vs-opponents were incorrectly applied to eagle2 design decisions. `name_collision` does NOT detect this (it checks node name conflicts with builtins, not data provenance). No test_suite.py check addresses data lineage or experimental validity. Requires metadata provenance tracking.

> **Note on BUG-4:** Per the subtask spec, BUG-4 "should be marked as detected by name_collision check." However, upon careful analysis, `name_collision` checks whether custom node names shadow builtin pyd names — it does **not** validate whether data used to parameterize those nodes came from appropriate agent matchups. The connection is that if an agent name appeared in both `BUILTIN_NODES` and `collect_phase1.py`'s `AGENTS` list, a collision would surface, but this is coincidental rather than intentional detection of BUG-4's data provenance issue. We mark this as ❌ for honest assessment.

**BUG-5 (Accelerate Intent Conflict):** This is a semantic label mapping issue in `proto_net.py`'s `NODE_TO_INTENT` dict. No YAML structural check can detect cross-module semantic conflicts in training label definitions.

### Detection Coverage Summary

| Metric | Value |
|--------|-------|
| Total known bugs | 5 |
| Bugs detected by test_suite.py | **1** (BUG-2 via `dead_code`) |
| Bugs partially detectable | 0 |
| Bugs undetectable by structural checks | **4** (BUG-1, BUG-3, BUG-4, BUG-5) |
| **Detection rate** | **20%** |

**Root cause of low detection:** test_suite.py validates **YAML structure** only. 4 of 5 bugs are **cross-module semantic issues** (unit mismatches, data provenance, label conflicts, feature dead weight) that require runtime assertions, data validation, or integration tests.

### CI Integration Readiness Assessment

| Criterion | Status | Evidence |
|-----------|--------|----------|
| **Exit codes** | ✅ Ready | `main()` calls `sys.exit(1)` when any test fails (line 407). Exit code 0 on all-pass. CI can gate on exit code. |
| **CLI interface** | ✅ Ready | Supports `--test <name>` for single test and `--all` for full suite. Agent name as positional arg. |
| **Determinism** | ✅ Deterministic | All 5 checks are pure structural analysis — no randomness, no network calls, no simulation dependency. Same input always produces same output. |
| **Execution time** | ✅ Fast | File I/O + text parsing only. Sub-second execution expected for any agent. |
| **Output format** | ⚠️ Human-only | Outputs `[PASS]`/`[FAIL]` text to stdout. No machine-readable format (JSON/JUnit XML). CI would need to parse exit code only, not individual test results. |
| **Multi-agent support** | ❌ Single-agent | Only tests one agent per invocation. CI would need a wrapper script to iterate over all agents in `submissions/` and `examples/`. |
| **Error isolation** | ✅ Good | Each test wrapped in try/except (line 373-376). One test exception doesn't block others. |
| **Hardcoded paths** | ⚠️ Fragile | `_load_init_params` hardcodes `examples.adaptive_eagle.nodes` as the import module path (line 158). Breaks for agents outside this directory. `PROJECT_ROOT` derived from `__file__` — works if run from project root but fragile under CI working directory changes. |
| **Dependencies** | ✅ Minimal | Only requires `pyyaml` + stdlib. No simulation, no PyTorch, no compiled `.pyd` dependencies for core checks. `importlib`-based param loading is optional (text fallback exists). |

### CI Readiness Verdict

**test_suite.py is CI-ready for single-agent gating** with minor improvements needed:

1. **Ready now:** Can be added to CI as `python tools/test_suite.py <agent_name>` with exit code check. Deterministic, fast, minimal dependencies.
2. **Needed for production CI:**
   - Multi-agent wrapper script (iterate `submissions/*/`)
   - Machine-readable output (JSON or JUnit XML) for CI dashboard integration
   - Fix hardcoded `examples.adaptive_eagle.nodes` module path in `_load_init_params`
   - Add `--json` output flag for programmatic consumption

### Recommendations for Closing Detection Gaps

| Gap | Bug(s) | Recommended New Check | Complexity |
|-----|--------|----------------------|------------|
| Runtime value range validation | BUG-1 | Assert angle features in `obs_dict_to_tensor` are in degree range (0–360) not radian range (0–2π) | Low |
| Feature variance profiling | BUG-3 | Check that all one-hot dimensions in training data have non-zero activation rate >1% | Medium |
| Data provenance tracking | BUG-4 | Validate that `collect_phase1.py` AGENTS list includes the target agent when deriving design parameters | Medium |
| Cross-module label consistency | BUG-5 | Verify `NODE_TO_INTENT` mapping is consistent with each agent's tactical usage of that action | High |
| Architectural completeness | BUG-2 (enhanced) | Promote `dead_code` finding to CRITICAL when unused imports include EIM nodes (intent pipeline disconnection) | Low |

---

## 4. Remaining Test File Effectiveness Analysis

This section analyzes the 5 remaining test-like files across the project: 3 in `tools/` and 2 in `LAG/tests/`.

---

### 4.1 `tools/test_agent.py` (115 LOC) — **Smoke Test**

**SE Category:** Smoke Test (manual CLI tool)

**What It Does:** CLI entry point that runs an agent vs an opponent for N rounds via `BehaviorTreeMatch`, printing win/loss summary. Not a unit test — it's an interactive developer tool.

**Assertion Analysis:**
| Assertion Type | Count | Description |
|---------------|-------|-------------|
| Explicit `assert` | 0 | No assert statements anywhere |
| Error handling | 1 | `FileNotFoundError` raised by `get_agent_path()` for missing agents |
| Implicit validation | 1 | `sys.exit(1)` on agent-not-found; exit code 0 otherwise |

**Assertion Quality:** ⚠️ **Low** — No assertions on match results, win rates, or output correctness. The script prints results but never validates them programmatically. A match that crashes silently or returns garbage would show no error.

**Automation Feasibility:** ⚠️ **Medium**
- `get_agent_path()` is a pure function extractable for unit testing (path resolution logic with 4 search locations)
- `main()` requires full sim environment (BehaviorTreeMatch → JSBSim)
- Could be wrapped as a smoke test by checking exit code, but provides no assertion value beyond "didn't crash"

**Determinism:** ❌ **Non-deterministic** — Match outcomes depend on simulation physics. Same agent pair can produce different results across runs due to floating-point accumulation in JSBSim. Seeding not exposed via CLI.

**Key Limitations:**
- No structured output (JSON/machine-readable) — stdout only
- No timeout or hang detection
- Cannot distinguish between "agent lost" and "agent errored"

---

### 4.2 `tools/test_intent_live.py` (57 LOC) — **Integration Verification Script**

**SE Category:** Integration Test (manual, non-automated)

**What It Does:** Monkey-patches `shared_state.set_intent` to intercept all EIM predictions during a hardcoded eagle2-vs-eagle1 match. Prints confidence distribution histogram and top-10 predictions. Verifies the EIM pipeline is wired end-to-end.

**Assertion Analysis:**
| Assertion Type | Count | Description |
|---------------|-------|-------------|
| Explicit `assert` | 0 | No assert statements |
| Conditional checks | 2 | `if raw_log:` and `if non_unknown:` guard empty-data branches |
| Implicit validation | 0 | No exit code, no pass/fail determination |

**Assertion Quality:** ❌ **None** — Purely observational. Prints data for human inspection but never validates: no check that predictions exist, no confidence threshold validation, no intent distribution sanity check. A completely broken EIM returning all-UNKNOWN would print "전체 예측이 UNKNOWN" but exit successfully.

**Automation Feasibility:** ⚠️ **Medium**
- The monkey-patching pattern is reusable for automated integration tests
- Adding assertions is straightforward: `assert len(raw_log) > 0`, `assert len(non_unknown) > 0`, `assert max(x[2] for x in raw_log) > 0.35`
- Hardcoded agent paths (eagle2/eagle1) limit generalizability
- Requires full sim environment

**Determinism:** ❌ **Non-deterministic** — Match simulation produces varying trajectories; EIM predictions depend on exact observation sequences. Confidence values and intent distributions will vary across runs.

**Key Limitations:**
- Hardcoded to eagle2-vs-eagle1 — not parameterizable
- No pass/fail exit code
- Monkey-patching approach is fragile (breaks if `shared_state.set_intent` signature changes)

---

### 4.3 `tools/test_dogfight2_connection.py` (110 LOC) — **Connection Test**

**SE Category:** Connection/Connectivity Test (manual, interactive)

**What It Does:** Interactive script that tests TCP connection to Dogfight 2 visualization server. Prompts user for host/port, attempts connection, queries plane list, reads plane state, and tests plane initialization.

**Assertion Analysis:**
| Assertion Type | Count | Description |
|---------------|-------|-------------|
| Explicit `assert` | 0 | No assert statements |
| Boolean checks | 3 | `if not client.connect()`, `if len(planes) > 0`, `if client.initialize_planes(2)` |
| Exit code | 1 | `sys.exit(0 if success else 1)` — proper pass/fail signaling |

**Assertion Quality:** ⚠️ **Low** — Checks connection success and plane count but no validation of plane state values (position, heading, speed could be NaN/zero/garbage). No timeout assertions. No protocol version check.

**Automation Feasibility:** ❌ **Low**
- Requires running Dogfight 2 server (external process, not in CI)
- Uses interactive `input()` for host/port — cannot run unattended without modification
- Would need mock TCP server for automated testing
- Connection-specific — no reusable test patterns

**Determinism:** ✅ **Deterministic** (given same server state) — TCP connection and state queries are deterministic. However, requires external server, making it environment-dependent.

**Key Limitations:**
- Interactive `input()` calls block automated execution
- External service dependency (Dogfight 2 must be running)
- No connection timeout configuration
- Error messages in Korean only — non-localizable CI output

---

### 4.4 `LAG/tests/test_jsbsim.py` (405 LOC) — **Legacy Environment Tests**

**SE Category:** Integration Test (automated, pytest-based)

**What It Does:** Comprehensive pytest suite for the LAG (LearningAgentsForAirCombat) JSBSim environment wrappers. Tests 4 environment types (SingleControl, SingleCombat, MultipleCombat) across multiple configurations with vectorized environment variants.

**Assertion Analysis:**
| Assertion Type | Count | Description |
|---------------|-------|-------------|
| Shape assertions | ~25 | `obs.shape == obs_shape`, reward/done shape checks across all env types |
| Value assertions | ~15 | `np.linalg.norm(obs - obs_buf[t]) < 1e-8` (reproducibility), reward magnitude checks (`< -100`, `< -50`) |
| State assertions | ~10 | Agent count, partner/enemy counts, done flags, missile alive status |
| Parameterized configs | 6+3+3+6 = 18 | Pytest parametrize across env configs and vectorized wrappers |

**Total assertion density:** ~50 assertions across 405 LOC = **~0.12 assertions/LOC** — high quality.

**Assertion Quality:** ✅ **High**
- Tests data contract (observation/action/reward shapes) exhaustively
- Reproducibility test (same seed → same trajectory) validates determinism
- Edge case testing: agent crash, agent shotdown, missile lifecycle
- Cross-validates DummyVecEnv vs SubprocVecEnv behavior equivalence

**Automation Feasibility:** ✅ **High**
- Standard pytest with `@pytest.mark.parametrize` — fully automated
- Clean setup/teardown (env.close() in vec tests)
- Self-contained seed management for reproducibility

**Determinism:** ✅ **Deterministic** — All tests use `env.seed(0)` + `action_space.seed(0)`. Reproducibility is explicitly tested (same seed → same observations within 1e-8 tolerance).

**Legacy Relevance to Current Pipeline:** ⚠️ **Indirect**
- Tests LAG's `envs.JSBSim.*` classes, which are the **upstream simulation environment** that `src/simulation/` compiled modules wrap
- The SDK's `BehaviorTreeMatch` → `runner_core.py` → compiled `src/simulation/` → JSBSim chain means these tests validate the foundational layer
- However, these tests are in `LAG/tests/` and test LAG-specific wrappers (`DummyVecEnv`, `SubprocVecEnv`, `ShareDummyVecEnv`), not the SDK's compiled `.pyd` wrappers
- **Gap:** No equivalent integration tests exist for the SDK's compiled simulation layer

**Key Limitations:**
- Requires JSBSim native library installation (C++ dependency)
- `TestJSBSimRunner.test_training` runs actual training loops (slow, ~minutes per parametrized case)
- Tests LAG environment API, not SDK environment API — coverage doesn't transfer directly
- `from envs.JSBSim.core.simulatior import MissileSimulator` — typo in module name ("simulatior") suggests legacy code quality issues

---

### 4.5 `LAG/tests/test_ppo.py` (175 LOC) — **Legacy Algorithm Tests**

**SE Category:** Unit Test (automated, pytest-based)

**What It Does:** Pytest suite for PPO (Proximal Policy Optimization) algorithm components: actor network, critic network, replay buffer, and full trainer. Tests across multiple observation/action space types.

**Assertion Analysis:**
| Assertion Type | Count | Description |
|---------------|-------|-------------|
| Shape assertions | ~12 | Action, log_prob, value, rnn_state output shapes |
| Batch count | 1 | `assert batch_count == num_mini_batch` — buffer iteration correctness |
| Parameterized combos | 4×2 + 1×2 + 2×1×4×2×2 + 2×1×4 = 50+ | Exhaustive parametrize over obs_space, act_space, batch_size, num_agents, mini_batch, chunk_length |

**Total assertion density:** ~13 explicit assertions × 50+ parametrized combos = **650+ effective assertion executions** — very high coverage.

**Assertion Quality:** ✅ **High**
- Tests all 4 action space types (Discrete, MultiDiscrete, MultiBinary, Box) — comprehensive interface contract validation
- Actor forward pass + evaluate_actions tested independently
- Buffer insert → compute_returns → generator pipeline tested end-to-end
- Trainer.train() smoke test verifies full gradient step without crash

**Automation Feasibility:** ✅ **High**
- Standard pytest — fully automated
- CPU-only (`device=torch.device("cpu")`) — no GPU dependency
- Fast execution (synthetic data, small networks: hidden_size=default)

**Determinism:** ✅ **Deterministic** — Uses fixed observation/action space samples. No random seeds needed for shape assertions. Trainer test may have non-deterministic gradient values but only checks "doesn't crash."

**Legacy Relevance to Current Pipeline:** ⚠️ **Low-Medium**
- PPO algorithm is used in LAG's RL training pipeline, which produces the baseline policy that `tools/query_lag_policy.py` queries
- The SDK does not use PPO directly — BT agents use behavior trees, not RL policies
- `tools/distill_lag_dt.py` distills the LAG policy into decision tree rules, so PPO correctness indirectly affects BT node parameterization
- **Gap:** No tests exist for the distillation pipeline (`distill_lag_dt.py`) that bridges LAG PPO → SDK BT nodes

**Key Limitations:**
- Requires PyTorch + gymnasium — heavier dependency than SDK core
- Tests algorithm correctness in isolation, not integration with JSBSim environment
- `get_config().parse_args(args='')` uses default config — doesn't test non-default hyperparameters
- No gradient value assertions — only shape checks and "didn't crash" verification

---

### 4.6 Test Effectiveness Summary

| File | SE Category | Assertions | Quality | Automation | Determinism | Pipeline Relevance |
|------|------------|------------|---------|------------|-------------|-------------------|
| `tools/test_agent.py` | Smoke | 0 explicit | ⚠️ Low | ⚠️ Medium | ❌ Non-det | Direct (CLI tool) |
| `tools/test_intent_live.py` | Integration | 0 explicit | ❌ None | ⚠️ Medium | ❌ Non-det | Direct (EIM verification) |
| `tools/test_dogfight2_connection.py` | Connection | 0 explicit | ⚠️ Low | ❌ Low | ✅ Det (env-dep) | Peripheral (visualization) |
| `LAG/tests/test_jsbsim.py` | Integration | ~50 | ✅ High | ✅ High | ✅ Deterministic | Indirect (upstream env) |
| `LAG/tests/test_ppo.py` | Unit | ~13 (×50+) | ✅ High | ✅ High | ✅ Deterministic | Low (RL algorithm) |

**Key Finding:** The 3 `tools/` test files have **zero assertions** — they are developer diagnostic scripts, not automated tests. The 2 `LAG/tests/` files are proper pytest suites with high assertion density and determinism, but they test the **legacy upstream** (JSBSim env, PPO algorithm), not the SDK pipeline itself. **No automated tests exist for the SDK's own tools/ or src/ modules.**

---

## 5. Bug Detection Matrix

This matrix analyzes each known bug (BUG-1 through BUG-5 from `PIPELINE_AUDIT.md`) against standard SE test types to determine what testing would have caught it, whether any existing test could have detected it, and the gap that allowed it to persist.

### 5.1 Matrix

| Bug ID | Severity | Root Cause | Test Type That Would Catch It | Existing Test Coverage | Gap That Allowed It |
|--------|----------|-----------|-------------------------------|----------------------|---------------------|
| **BUG-1** | CRITICAL | Angular features passed as radians at inference but trained on degrees — `runner.py` feeds raw `obs_dict` (radians) to `obs_dict_to_tensor`, while CSVs store `×180` (degrees). Normalization constants (`NORM_MEAN`, `NORM_STD`) designed for degree scale. | **Data Validation + Integration Test** — A data validation test asserting input feature ranges match training distribution (e.g., `assert 0 <= ata_deg <= 180` at inference entry point), or an integration test comparing `obs_dict_to_tensor` output between training CSV path and live inference path for the same physical state. | ❌ **None.** No test validates that inference-time feature values are in the same domain as training-time values. `test_suite.py` checks structural YAML correctness but has zero data-level checks. `test_intent_live.py` prints EIM predictions but never asserts on feature value ranges or normalization consistency. | **No train/inference parity validation.** The pipeline has no contract test enforcing that the data encoding path used during training (`collect_phase1.py` → CSV → `encoder.py`) produces the same tensor representation as the live inference path (`runner.py` → `obs_dict_to_tensor`). The two paths were developed independently with no shared validation. |
| **BUG-2** | CRITICAL | EIM nodes (`EnemyIntentIs`, `EnemyIntentConfidence`, `SelectStrategy`) are imported in `nodes/__init__.py` but never referenced in `adaptive_eagle.yaml`. The intent prediction runs every step but no BT branch reads it. | **Static Analysis + Integration Test** — `test_suite.py`'s existing `dead_code` check detects unused imports, but treats it as LOW severity. An integration test asserting that `shared_state.intent` influences at least one BT condition evaluation would catch the disconnection. | ⚠️ **Partial.** `test_suite.py` has a `dead_code` check that flags imported-but-unused nodes. It *does* detect EIM nodes as unused. However, it classifies all dead code equally and does not escalate EIM disconnection to CRITICAL — it cannot distinguish "cosmetic dead code" from "core pipeline disconnection." | **Severity-blind static analysis.** The `dead_code` check exists but lacks semantic awareness: it flags `EnemyIntentIs` as unused with the same severity as any other dead import. No integration test verifies that the EIM→BT feedback loop is functionally connected end-to-end. The architectural intent ("adaptive response") has no test that validates the adaptation actually occurs. |
| **BUG-3** | WARNING | `encoder.py` defines 7 BFM classes (`OBFM, DBFM, HABFM, UNKNOWN, UNK_NEAR_OFF, UNK_SCISSORS, UNK_DISENGAGING`) but runtime and training data only ever produce the first 4. Three one-hot dimensions are permanently zero — dead feature weight. | **Data Validation + Unit Test** — A data validation test checking that every one-hot dimension in the training dataset has activation rate >1%, or a unit test asserting `BFM_CLASSES` matches the set of values actually produced by `MatchCore.pyd`. | ❌ **None.** No test validates feature activation statistics on training data. No test compares `encoder.py`'s class list against the runtime engine's actual output vocabulary. `test_suite.py` checks node names and YAML structure but has no feature-level or data-level validation. | **No feature provenance validation.** The encoder's class vocabulary was defined speculatively (including planned-but-unimplemented sub-classifications) without a contract test binding it to the simulation engine's actual output. No data profiling step exists in the training pipeline to flag zero-variance features before model training. |
| **BUG-4** | CRITICAL | SAE/TIR/WCS statistics used to justify `adaptive_eagle` BT node design were derived from `eagle1` vs non-eagle opponents (Phase 1 collection). `collect_phase1.py` AGENTS list does not include `eagle2` or `adaptive_eagle` — the design parameters apply to the wrong tactical context. | **Data Validation + Regression Test** — A data provenance test asserting that the agent(s) referenced in BT node design comments exist in `collect_phase1.py`'s AGENTS list, or a regression test that re-derives SAE/TIR from the correct agent matchups and compares against the hardcoded values in custom action nodes. | ❌ **None.** No test validates that the data source (AGENTS list) matches the data consumer (BT node design). The statistics are hardcoded in comments (`TIR: Scissors→Accelerate→OBFM 51.6%`) with no traceability to the collection that produced them. No automated re-derivation or staleness check exists. | **No data provenance chain.** The pipeline has no mechanism to link derived statistics back to their source data and validate applicability. Phase 1 collection and BT node design are decoupled processes with no automated consistency check — a human must manually verify that collected data matches the deployment context. |
| **BUG-5** | WARNING (latent) | `proto_net.py` maps `Accelerate` → `PURSUIT`, but `adaptive_eagle.yaml` uses `Accelerate` for circular orbit escape (neutral/anti-deadlock intent). If `adaptive_eagle` is added to Phase 1 collection, orbit-escape steps will be mislabeled as PURSUIT in EIM training data. | **Unit Test + Static Analysis** — A unit test asserting that `NODE_TO_INTENT` mappings are consistent across all agents that could appear in training data (checking each agent's YAML to verify the tactical intent of each action matches the label). A static analysis rule flagging when the same action node has different semantic purposes across agents. | ❌ **None.** No test validates cross-agent semantic consistency of `NODE_TO_INTENT`. The mapping is defined once in `proto_net.py` with no per-agent override mechanism or validation. `test_suite.py` does not check label correctness — only structural YAML validity. | **Global label assumption without per-agent context.** `NODE_TO_INTENT` assumes a single global mapping from action names to intent labels, but action semantics are agent-dependent (same node, different tactical purpose). No test validates this assumption, and no mechanism exists to define agent-specific label overrides. The bug is latent because `adaptive_eagle` is not yet in the collection AGENTS list. |

### 5.2 Detection Gap Analysis

**Pattern 1: No data-level validation exists anywhere in the pipeline.**
BUG-1, BUG-3, and BUG-4 are all data bugs — wrong values, dead features, wrong data source. The pipeline has structural validation (`test_suite.py`) but zero data validation. No test checks feature ranges, distribution properties, value domains, or data provenance.

**Pattern 2: `test_suite.py` is severity-blind.**
BUG-2 demonstrates that even when a check *exists* (dead_code), it lacks the semantic context to escalate correctly. All dead code findings are treated equally, so a cosmetic unused import and a complete pipeline disconnection produce the same low-severity warning.

**Pattern 3: Cross-module contracts are untested.**
BUG-1 (encoder vs runner), BUG-4 (collect vs design), and BUG-5 (proto_net vs YAML) are all cross-module interface bugs where two components make incompatible assumptions. No integration tests validate these cross-module contracts.

**Pattern 4: Latent bugs have no prevention mechanism.**
BUG-5 is currently harmless but will activate when `adaptive_eagle` enters the AGENTS list. No guard test exists to catch this at the point of AGENTS list modification — the bug will silently corrupt training data.

### 5.3 Test Type Coverage Gap Summary

| SE Test Type | Bugs It Would Catch | Currently Exists? | Priority |
|-------------|---------------------|-------------------|----------|
| **Data Validation** | BUG-1, BUG-3, BUG-4 | ❌ None | **P0 — Critical** |
| **Integration Test** (cross-module) | BUG-1, BUG-2 | ❌ None | **P0 — Critical** |
| **Unit Test** (pure logic) | BUG-3, BUG-5 | ❌ None | **P1 — High** |
| **Static Analysis** (semantic) | BUG-2, BUG-5 | ⚠️ Partial (`test_suite.py` structural only) | **P1 — High** |
| **Regression Test** | BUG-4 | ❌ None | **P2 — Medium** |
| **E2E Test** | All (indirectly) | ❌ None | **P2 — Medium** |

---

## 6. Statistical Rigor Assessment — Wilson CI Verification

### 6.1 Wilson CI Formula Comparison (Code vs Textbook)

**Textbook Wilson Score Interval** (as documented in `ADAPTIVE_BT_PLAN.md` §1a):

$$\text{CI}_{95\%} = \frac{\hat{p} + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat{p}(1-\hat{p}) + \frac{z^2}{4n}}{n}}}{1 + \frac{z^2}{n}}, \quad z=1.96$$

**Code implementation** (`tools/evaluate.py`, `_wilson_ci()`):

```python
def _wilson_ci(wins: int, total: int, z: float = 1.96) -> tuple:
    if total == 0:
        return (0.0, 0.0)
    p = wins / total
    denom = 1 + z * z / total           # = 1 + z²/n  ✅
    centre = (p + z * z / (2 * total)) / denom  # = (p̂ + z²/(2n)) / (1 + z²/n)  ✅
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    #       = z × √((p̂(1-p̂) + z²/(4n)) / n) / (1 + z²/n)  ✅
    lo = max(0.0, centre - margin)       # clamp to [0, 1]  ✅
    hi = min(1.0, centre + margin)       # clamp to [0, 1]  ✅
    return (round(lo, 4), round(hi, 4))
```

**Verdict: ✅ CORRECT** — The implementation exactly matches the textbook Wilson Score Interval formula. Each component maps 1:1:

| Formula Component | Variable | Code Expression | Match |
|---|---|---|---|
| $\hat{p}$ | `p` | `wins / total` | ✅ |
| $1 + z^2/n$ | `denom` | `1 + z * z / total` | ✅ |
| $\hat{p} + z^2/(2n)$ | centre numerator | `p + z * z / (2 * total)` | ✅ |
| $z\sqrt{(\hat{p}(1-\hat{p}) + z^2/(4n))/n}$ | `margin` (before /denom) | `z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)` | ✅ |
| Division by $1 + z^2/n$ | `/denom` on both centre and margin | ✅ | ✅ |
| Clamping to [0, 1] | `max(0, ...)`, `min(1, ...)` | Standard Wilson practice | ✅ |

### 6.2 Boundary Case Analysis

| Case | Input | Expected Behavior | Code Behavior | Verdict |
|---|---|---|---|---|
| **total = 0** | `_wilson_ci(0, 0)` | Undefined; should not crash | Returns `(0.0, 0.0)` — early return guard | ✅ Safe (degenerate but non-crashing) |
| **p = 0** (0 wins) | `_wilson_ci(0, 100)` | CI should be near 0 but not exactly 0 (Wilson advantage over normal approx) | `centre = z²/(2n) / (1+z²/n)`, `margin > 0` → `lo = max(0, centre - margin) = 0.0`, `hi > 0`. Returns `(0.0, 0.0362)` | ✅ Correct — lower bound clamped to 0, upper bound positive. Wilson properly avoids the degenerate [0, 0] CI that normal approximation would produce. |
| **p = 1** (all wins) | `_wilson_ci(100, 100)` | CI should be near 1 but not exactly 1 | `p(1-p) = 0`, only z²/(4n) term contributes to margin. Returns `(0.9638, 1.0)` | ✅ Correct — upper bound clamped to 1, lower bound < 1. Symmetric to p=0 case. |
| **p = 0.5, small n** | `_wilson_ci(5, 10)` | Wide CI reflecting high uncertainty | Returns `(0.2368, 0.7632)` — width ≈ 52.6% | ✅ Appropriately wide for n=10 |
| **wins > total** | `_wilson_ci(150, 100)` | Invalid input — p > 1 | `p = 1.5`, sqrt argument can go negative → `math.sqrt` raises `ValueError` | ⚠️ **No input validation.** No guard against `wins > total`. In practice, callers always pass valid counts, but defensive programming would add an assertion. |
| **negative inputs** | `_wilson_ci(-5, 100)` | Invalid input | `p = -0.05`, proceeds without error, produces nonsensical CI | ⚠️ **No input validation.** Same as above — no guard on negative values. |

**Boundary Verdict:** ✅ **Correct for all valid inputs.** The `total = 0` edge case is properly handled. The `p = 0` and `p = 1` boundaries demonstrate Wilson's key advantage over normal approximation (non-degenerate CIs). ⚠️ Minor gap: no defensive validation for invalid inputs (`wins > total`, negative values), though these are never produced by the calling code.

### 6.3 CI Width Verification for Claimed Sample Sizes

`ADAPTIVE_BT_PLAN.md` §0.2 claims:

> "$n = 695 \times 10 = 6950$ 매치일 때 Wilson $\text{CI}_{95\%}$ at 50% WR $\approx \pm 1.18\%$"

And the subtask spec claims: "695×50R = ±0.53%"

**Manual computation** using the Wilson formula at p = 0.5, z = 1.96:

#### Case 1: n = 6,950 (695 opponents × 10 rounds)

```
p = 0.5, n = 6950, z = 1.96
denom = 1 + 1.96² / 6950 = 1 + 3.8416 / 6950 = 1.000553
centre = (0.5 + 3.8416 / 13900) / 1.000553 = (0.5 + 0.000276) / 1.000553 = 0.500000 (approx)
margin_numerator = 1.96 × √((0.25 + 3.8416/27800) / 6950)
                 = 1.96 × √((0.25 + 0.0001382) / 6950)
                 = 1.96 × √(0.2501382 / 6950)
                 = 1.96 × √(0.00003599)
                 = 1.96 × 0.005999
                 = 0.01176
margin = 0.01176 / 1.000553 = 0.01175
```

**Result: ±1.175% ≈ ±1.18%** ✅ **Claim verified.**

#### Case 2: n = 34,750 (695 opponents × 50 rounds)

```
p = 0.5, n = 34750, z = 1.96
denom = 1 + 3.8416 / 34750 = 1.0001106
centre ≈ 0.5
margin_numerator = 1.96 × √((0.25 + 3.8416/139000) / 34750)
                 = 1.96 × √((0.25 + 0.00002764) / 34750)
                 = 1.96 × √(0.2500276 / 34750)
                 = 1.96 × √(0.000007194)
                 = 1.96 × 0.002682
                 = 0.005257
margin = 0.005257 / 1.0001106 = 0.005256
```

**Result: ±0.526% ≈ ±0.53%** ✅ **Claim verified.**

#### Comparison with Normal Approximation

For reference, the normal approximation CI at p = 0.5 is $\pm z\sqrt{p(1-p)/n} = \pm 1.96\sqrt{0.25/n}$:

| n | Wilson CI width (±%) | Normal approx (±%) | Difference |
|---|---|---|---|
| 6,950 | ±1.175% | ±1.176% | 0.001% — negligible at large n |
| 34,750 | ±0.526% | ±0.526% | <0.001% — negligible at large n |
| 10 | ±26.4% (Wilson) | ±31.0% (Normal) | 4.6% — Wilson is tighter and doesn't overshoot [0,1] |

**Key insight:** At the large sample sizes used in the pipeline (n ≥ 6,950), the Wilson and normal approximation converge. Wilson's advantage is primarily at small n (per-opponent intervals with rounds=10, n=10) where normal approximation can produce CIs outside [0, 1].

### 6.4 Overall Correctness Assessment

| Criterion | Verdict | Details |
|---|---|---|
| **Formula correctness** | ✅ **Correct** | Code exactly matches textbook Wilson Score Interval |
| **Boundary behavior** | ✅ **Correct** | Proper handling of total=0, p=0, p=1; clamping to [0,1] |
| **Claimed CI widths** | ✅ **Verified** | 695×10R → ±1.18%, 695×50R → ±0.53% confirmed by manual computation |
| **Choice of Wilson over Normal** | ✅ **Justified** | Wilson provides correct boundary behavior for per-opponent CIs (n=10–50) where normal approximation is unreliable |
| **Input validation** | ⚠️ **Missing** | No guard against wins > total or negative inputs (low risk — callers are well-behaved) |
| **Rounding** | ✅ **Appropriate** | `round(lo, 4)` and `round(hi, 4)` provide 0.01% precision — sufficient for percentage-level reporting |
| **z-value default** | ✅ **Standard** | z=1.96 for 95% CI is the standard two-tailed critical value |

**Overall: The Wilson CI implementation is statistically correct and the claims in ADAPTIVE_BT_PLAN.md are verified.** The only improvement opportunity is adding defensive input validation for `wins > total` (a minor robustness concern, not a correctness issue).

---

## 7. Statistical Rigor Assessment — CMA-ES Fitness Evaluation

### 7.1 Fitness Function Analysis

**Scoring constants** (`adaptive_optimizer.py` lines 38–41):

```python
WIN_BASE  = 10.0
DRAW_BASE =  1.0
LOSS_BASE = -5.0
HP_WEIGHT =  2.0
```

**`compute_score()` formula** (lines 373–380):

```python
hp_diff = clamp((our_hp - their_hp) / 100.0, -1, 1)
score = BASE + hp_diff × HP_WEIGHT
```

Where `BASE` ∈ {WIN_BASE, DRAW_BASE, LOSS_BASE} depending on match outcome.

#### 7.1.1 Score Range Analysis

| Outcome | hp_diff = -1 (worst) | hp_diff = 0 | hp_diff = +1 (best) |
|---------|---------------------|-------------|---------------------|
| **WIN** | 10 + (-1)×2 = **8.0** | 10 + 0 = **10.0** | 10 + 1×2 = **12.0** |
| **DRAW** | 1 + (-1)×2 = **-1.0** | 1 + 0 = **1.0** | 1 + 1×2 = **3.0** |
| **LOSS** | -5 + (-1)×2 = **-7.0** | -5 + 0 = **-5.0** | -5 + 1×2 = **-3.0** |

#### 7.1.2 Hierarchical Guarantee Proof

**Required property:** worst_win > best_draw > best_loss (strict hierarchy ensures CMA-ES always prefers wins over draws, and draws over losses, regardless of HP margin).

| Comparison | Left | Right | Gap | Satisfied? |
|-----------|------|-------|-----|-----------|
| **worst_win > best_draw** | 8.0 | 3.0 | **+5.0** | ✅ Yes |
| **best_draw > best_loss** | 3.0 | -3.0 | **+6.0** | ✅ Yes |
| **worst_win > best_loss** | 8.0 | -3.0 | **+11.0** | ✅ Yes (transitive) |

**Verdict: ✅ The hierarchical guarantee holds.** The WIN/DRAW/LOSS score bands are completely non-overlapping:

```
LOSS: [-7.0, -3.0]
DRAW: [-1.0, +3.0]
WIN:  [+8.0, +12.0]
```

The gap between the worst win (8.0) and the best draw (3.0) is +5.0 — a comfortable margin. This means CMA-ES will **never** prefer a high-HP draw over a low-HP win, which is the correct optimization priority. The HP_WEIGHT (2.0) is small enough relative to the base gaps (WIN−DRAW = 9, DRAW−LOSS = 6) that it cannot cause band overlap.

**Formal constraint for non-overlap:** `HP_WEIGHT < (WIN_BASE - DRAW_BASE) / 2`. Current: `2.0 < (10-1)/2 = 4.5` ✅. Maximum safe HP_WEIGHT before WIN/DRAW overlap: **4.5**.

#### 7.1.3 Fitness Landscape Properties

**Gradient informativeness:** The HP_WEIGHT term provides within-band gradient — CMA-ES can distinguish a close win from a dominant win, and a near-draw loss from a blowout loss. Without HP_WEIGHT (pure W/D/L scoring), the fitness landscape would be a step function with large flat plateaus, making CMA-ES gradient estimation ineffective.

**Score aggregation:** `evaluate_fitness()` sums scores across all 40 opponents (`total_score += score`). This means:
- Total score range: 40 × [-7, +12] = [-280, +480]
- A perfect agent (40 dominant wins): +480
- A baseline agent (e.g., 50% WR, mixed HP): ~40 × (0.5×10 + 0.5×(-5)) = +100

**Potential issue — equal opponent weighting:** All 40 sampled opponents contribute equally to the fitness sum. This means an agent that dominates 39 easy opponents but consistently loses to 1 hard opponent may score higher than an agent that beats all 40 with moderate margins. The fitness function optimizes for **average performance**, not worst-case robustness.

### 7.2 Stratified Sampling Bias Assessment

**Sampling method** (`_stratified_sample_opponents`, lines 58–79):

1. Load opponent pool manifest (695 opponents across 6 layers)
2. Group opponents by layer
3. Allocate `per_layer = max(1, k // len(by_layer))` = max(1, 40//6) = **6 per layer**
4. Randomly sample up to `per_layer` from each layer
5. Fill remaining slots (40 - 6×6 = 4) from unsampled opponents

**Layer distribution analysis** (assuming 6 layers):

| Layer | Pool Size | Sample Size | Sampling Rate |
|-------|-----------|-------------|---------------|
| L1 (Pure) | 90 | 6-7 | 6.7-7.8% |
| L2 (Gated) | 240 | 6-7 | 2.5-2.9% |
| L3 (Phase) | 120 | 6-7 | 5.0-5.8% |
| L4 (LHS) | ~100 | 6-7 | 6.0-7.0% |
| L5 (Cross) | ~100 | 6-7 | 6.0-7.0% |
| L6 (Counter) | ~45 | 6-7 | 13.3-15.6% |

**Bias assessment:**

1. **✅ Layer representation guaranteed:** Every layer gets ≥6 representatives. This prevents the optimizer from ignoring any tactical dimension.

2. **⚠️ Inverse proportion to layer size:** L2 (240 opponents, most diverse) gets the same 6–7 samples as L6 (45 opponents). This means L2's diversity is heavily undersampled — only 2.5% of its tactical space is tested during optimization. An agent could perform well against sampled L2 opponents but fail against unsampled ones.

3. **⚠️ Fixed seed (seed=0):** The sample is deterministic — `rng = random.Random(seed)`. The same 40 opponents are used for every CMA-ES evaluation throughout the entire optimization run. This means CMA-ES could **overfit to these specific 40 opponents** rather than finding a generally optimal solution. A rotating or resampling strategy per generation would reduce this risk.

4. **✅ Full pool validation exists:** `validate_on_full_pool()` runs the final agent against all 695 opponents, catching overfitting to the 40-sample subset. This is the correct two-stage approach (fast optimization → full validation).

5. **⚠️ Remainder fill is not stratified:** The 4 remainder slots (line 76–78) are filled randomly from all unsampled opponents, slightly biasing toward larger layers (L2 has more unsampled opponents, so it's more likely to fill remainder slots).

**Overall sampling verdict:** The stratified approach is **sound but could overfit** to the fixed 40-opponent sample. The full-pool validation step mitigates this, but the optimizer itself may converge to a local optimum that exploits specific weaknesses of the sampled subset.

### 7.3 Convergence Risk Analysis (104-Dimensional CMA-ES)

#### 7.3.1 Dimensionality vs Budget

| Parameter | Value |
|-----------|-------|
| Search dimensions | 104 |
| Default budget | 400 evaluations |
| Population size | `min(n_workers × 2, 40)` |
| Initial σ | 0.3 |
| Bounds | [0, 1] per dimension |

**CMA-ES convergence theory:** For a well-conditioned quadratic objective in d dimensions, CMA-ES typically requires O(d²) to O(d³) function evaluations to converge. For d = 104:
- Optimistic: 104² = **10,816 evaluations**
- Pessimistic: 104³ = **1,124,864 evaluations**
- Default budget: **400 evaluations**

**The default budget of 400 is approximately 25× too small for reliable convergence** in 104 dimensions. At 400 evaluations with popsize ≈ 40, the optimizer runs only ~10 generations. CMA-ES needs many more generations to learn the covariance structure (rotation and scaling of the search distribution).

#### 7.3.2 Mixed Discrete-Continuous Space

The 104 dimensions include:
- **8 binary** (enable flags): `[True, False]` encoded as [0, 1]
- **9 discrete slots** (action selection): 2–6 choices each, encoded as [0, 1]
- **~87 continuous** (node parameters): naturally [0, 1] mapped to physical ranges

**Problem:** CMA-ES is designed for continuous optimization. Discrete parameters are encoded via:

```python
idx = min(int(val * len(spec)), len(spec) - 1)
```

This maps the continuous [0, 1] to discrete bins. CMA-ES's covariance matrix adaptation will try to model correlations in the continuous space, but discrete parameters create **step-function discontinuities** in the fitness landscape. The covariance matrix cannot capture these discontinuities, degrading adaptation quality.

**Mitigation present:** The initial position (`x0`) is set to known-good defaults via `params_to_vector(defaults)`, which gives CMA-ES a head start near a reasonable solution. σ₀ = 0.3 limits initial exploration to roughly ±30% of each parameter's range.

#### 7.3.3 Noisy Fitness Evaluations

Each candidate is evaluated via **single-round matches** against 40 opponents (1 match per opponent). Match outcomes have inherent stochasticity from simulation physics.

**Impact on CMA-ES:** CMA-ES estimates the fitness landscape gradient from population rankings. With noisy fitness, rankings are unreliable — a slightly worse candidate may appear better due to favorable match randomness. This slows convergence and can cause the distribution to oscillate rather than contract.

**No noise-handling is implemented:** CMA-ES supports uncertainty handling (e.g., `CMA_on` option for noisy objectives, or re-evaluation of elites), but none is configured in the `opts` dict. The `tolfun: 1e-6` termination criterion is also very tight and may trigger prematurely when noise amplitude exceeds 1e-6.

### 7.4 Deceptive Optima Risk Assessment

A **deceptive optimum** is a local maximum that CMA-ES converges to because the fitness gradient points toward it from most starting points, even though a better global optimum exists elsewhere.

#### 7.4.1 Sources of Deceptive Optima

1. **Branch disable shortcuts:** Setting `enable_*` flags to False removes entire BT branches, reducing the agent to a simpler tree. A simple agent may achieve moderate win rates (e.g., always-pursue beats many weak opponents) with a high, stable fitness score. More complex agents (more branches enabled) have higher variance and may score lower during early exploration, causing CMA-ES to prematurely disable branches.

2. **Action slot homogeneity:** If `pursuit_action`, `default_action`, and `overshoot_action` all converge to the same node (e.g., SmartLeadPursuit), the agent becomes a specialist. This can score well against the fixed 40-sample opponents but poorly against the full 695-pool.

3. **Conditional parameter insensitivity:** Some condition thresholds (e.g., `IsHighEnergy.threshold`) only matter when their parent branch is enabled. If CMA-ES disables the branch early, the condition parameters become "free" dimensions that add noise without affecting fitness, inflating the effective dimensionality without providing gradient signal.

#### 7.4.2 Structural Mitigations Present

| Mitigation | Present? | Details |
|-----------|----------|---------|
| Default initialization at known-good point | ✅ | `x0 = params_to_vector(defaults)` starts near v5.1 baseline |
| Full-pool validation post-optimization | ✅ | `validate_on_full_pool()` catches overfitting to sample |
| σ₀ = 0.3 (conservative) | ✅ | Limits initial exploration to ±30%, preventing wild early jumps |
| Multiple restarts | ❌ | No restart mechanism — single CMA-ES run from one starting point |
| Population diversity maintenance | ❌ | No explicit diversity mechanism beyond CMA-ES's natural exploration |
| Ablation analysis | ✅ | `--ablation` CLI flag exists (referenced in docstring but not shown in code) |

#### 7.4.3 Risk Summary

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|-----------|
| Insufficient budget for 104-dim convergence | **HIGH** | Very likely at budget=400 | Increase budget to ≥5,000; or reduce effective dimensionality |
| Discrete parameter discontinuities | **MEDIUM** | Inherent in design | Consider separate discrete/continuous optimization or SMAC-style mixed optimization |
| Fixed-sample overfitting | **MEDIUM** | Likely with fixed seed=0 | Rotate sample per generation or use larger sample |
| Noisy single-round evaluations | **MEDIUM** | Inherent | Add re-evaluation of top candidates; or increase rounds per opponent |
| Premature branch disabling | **MEDIUM** | Moderate | Initialize all branches enabled; add exploration bonus for complexity |
| Deceptive local optima | **LOW-MEDIUM** | Possible | Multiple restarts from different x0; or CMA-ES with increasing population size (IPOP) |

### 7.5 Overall CMA-ES Fitness Evaluation Verdict

| Criterion | Verdict | Details |
|-----------|---------|---------|
| **Hierarchical score guarantee** | ✅ **Correct** | WIN > DRAW > LOSS bands are non-overlapping with 5.0+ point gaps |
| **HP gradient informativeness** | ✅ **Good** | HP_WEIGHT provides within-band gradient without breaking hierarchy |
| **Stratified sampling design** | ✅ **Sound** | Layer-balanced sampling ensures tactical coverage |
| **Sampling overfitting risk** | ⚠️ **Moderate** | Fixed 40-opponent sample throughout optimization; mitigated by full-pool validation |
| **Convergence feasibility** | ❌ **Insufficient budget** | 400 evals for 104 dims is ~25× below theoretical minimum; unlikely to find true optimum |
| **Mixed discrete-continuous handling** | ⚠️ **Suboptimal** | CMA-ES not designed for discrete parameters; continuous encoding creates discontinuities |
| **Noise handling** | ❌ **Missing** | Single-round evaluation with no re-evaluation or noise adaptation |
| **Deceptive optima resistance** | ⚠️ **Limited** | No restarts, no diversity maintenance; good default initialization partially mitigates |

**Summary:** The fitness function design is **mathematically sound** — the hierarchical guarantee holds and HP weighting is well-calibrated. The stratified sampling approach is reasonable with the full-pool validation safety net. However, the **optimization process itself is unlikely to find the true optimum** due to (1) grossly insufficient evaluation budget for 104 dimensions, (2) mixed discrete-continuous space degrading CMA-ES covariance adaptation, and (3) noisy single-round evaluations without noise handling. The pipeline's strength is its design (correct fitness, correct sampling, correct validation) rather than its convergence properties. Increasing the budget to 5,000+ and adding noise-robust evaluation (3–5 rounds per opponent) would substantially improve optimization quality.

## 8. Statistical Rigor Assessment — Seed Determinism & Reproducibility

### 8.1 Determinism Chain Analysis

The optimization pipeline has a 5-stage determinism chain. Each stage must be deterministic for end-to-end reproducibility:

```
CMA-ES Sampling → Parameter Decoding → YAML Generation → Match Execution → Fitness Aggregation
     [1]               [2]                  [3]               [4]              [5]
```

| Stage | Component | Seed-Controlled? | Deterministic? | Details |
|-------|-----------|-----------------|----------------|---------|
| **1. CMA-ES Sampling** | `cma.CMAEvolutionStrategy` | ✅ Yes (`seed` option) | ✅ Yes | `adaptive_optimizer.py` passes `'seed': seed` (default 42) to CMA-ES options. `bt_optimizer_v3.py` does the same. Given identical seed, CMA-ES produces identical sample sequences. |
| **2. Parameter Decoding** | `vector_to_params()` | N/A (pure function) | ✅ Yes | Pure mathematical transform: `np.clip` + linear scaling for continuous, index mapping for discrete. No randomness. Deterministic for identical input vectors. |
| **3. YAML Generation** | `build_bt_yaml()` / `_write_yaml()` | N/A (pure function) | ✅ Yes | Constructs dicts from ordered parameter lists, dumps with `sort_keys=False`. Python 3.7+ guarantees dict insertion order. No randomness in YAML construction. |
| **4. Match Execution** | `BehaviorTreeMatch` → `MatchCore` (.pyd) → JSBSim | ❌ No | ⚠️ **Uncertain** | No seed parameter passed to `MatchCore` or JSBSim. The `.pyd` compiled extension and JSBSim C++ internals are opaque. Potential FP non-determinism in physics integration (Runge-Kutta step accumulation). |
| **5. Fitness Aggregation** | Score formula + `np.mean` | N/A (pure function) | ✅ Yes | `WIN_BASE/DRAW_BASE/LOSS_BASE + HP_WEIGHT * hp_diff` is deterministic. Summation order is fixed (opponent list order). |

### 8.2 Identified Sources of Non-Determinism

#### Critical: Match Execution Layer (Stage 4)

1. **JSBSim Physics Engine (.pyd)** — Severity: **HIGH**
   - `runner_core.MatchCore` is a compiled `.pyd` extension; source unavailable for audit
   - JSBSim uses iterative ODE solvers (4th-order Runge-Kutta) where floating-point accumulation over 1000+ steps can diverge across platforms/compilers
   - No evidence of seed parameter being passed to `SingleCombatEnv` or `env.reset()`
   - **Impact:** Two runs with identical YAML agents may produce different HP outcomes, meaning the same candidate can receive different fitness scores

2. **Multiprocessing Result Ordering** — Severity: **MEDIUM**
   - `adaptive_optimizer.py` uses `pool.map()` (ordered) for evaluation — ✅ deterministic ordering
   - `bt_optimizer.py` uses `pool.imap_unordered()` in some paths — ⚠️ result arrival order varies
   - **Impact:** When results are aggregated by arrival order rather than index, fitness arrays may be shuffled. However, score aggregation uses `np.mean` which is commutative, so final fitness is unaffected. The non-determinism affects only logging/display order.

3. **Opponent Sampling Without Fixed Seed** — Severity: **LOW**
   - `_stratified_sample_opponents(k=40, seed=0)` uses a fixed seed — ✅ deterministic
   - Called once at module load time, producing the same 40 opponents every run

#### Minor: Optimizer-Specific Issues

4. **bt_optimizer.py Unseeded LHS Fallback** — Severity: **MEDIUM**
   - Lines 283, 302: `rng = np.random.default_rng()` creates unseeded RNG when `latin_hypercube_sample()` is called without explicit RNG argument
   - The main `run_search()` path (line 598) correctly seeds: `rng = np.random.default_rng(seed)` — but auxiliary/test calls may not
   - **Impact:** Ad-hoc calls to LHS sampling produce different candidates each run

5. **Thread-Level FP Non-Determinism** — Severity: **LOW**
   - Multiprocessing workers may execute on different CPU cores with different FP rounding modes (unlikely on modern x86-64 but possible with mixed SSE/AVX)
   - Python's `float()` conversion is deterministic, but C++ physics underneath is not guaranteed

### 8.3 Reproducibility Confidence Assessment

| Scope | Confidence | Rationale |
|-------|------------|-----------|
| **CMA-ES sample sequence** (same seed) | 🟢 **High** | CMA-ES library is well-tested; seed parameter is correctly propagated |
| **Parameter → YAML mapping** | 🟢 **High** | Pure functions with no randomness |
| **Single match outcome** (same agents) | 🟡 **Medium-Low** | JSBSim physics + compiled .pyd are opaque; no seed control at sim level; FP accumulation over 1000 steps may diverge |
| **Fitness of one candidate** (same agents, same opponents) | 🟡 **Medium-Low** | Depends on match determinism × number of opponents; variance compounds |
| **Full optimization run** (same seed, same machine) | 🟡 **Medium** | CMA-ES trajectory is deterministic IF fitness evaluations are identical; but match non-determinism means fitness noise propagates into CMA-ES covariance updates, causing trajectory divergence after ~10–20 generations |
| **Cross-machine reproducibility** | 🔴 **Low** | Different compilers, FP libraries, CPU architectures, and `mp.cpu_count()` all vary |

**Overall Reproducibility Confidence: MEDIUM-LOW**

The pipeline is deterministic from seed through YAML generation (stages 1–3), but the match execution layer (stage 4) is an opaque black box with no seed control. Since CMA-ES adapts its covariance matrix based on fitness rankings, even small match-level noise compounds into divergent optimization trajectories over hundreds of generations.

### 8.4 Recommendations for Determinism Testing

1. **Empirical Determinism Test (Priority: HIGH)**
   Run the same agent pair 10× with identical parameters and compare match outcomes (HP values, step counts, win/loss). This directly measures stage-4 variance without requiring source access to `.pyd` internals.

   ```python
   # Proposed test sketch
   def test_match_determinism():
       results = [run_match(agent_a, agent_b) for _ in range(10)]
       hp_values = [r.hp_agent1 for r in results]
       assert len(set(hp_values)) == 1, f"Non-deterministic: {hp_values}"
   ```

2. **Seed Propagation to MatchCore (Priority: HIGH)**
   If `MatchCore` or `SingleCombatEnv` accepts a seed parameter, propagate it from the optimizer. Check `runner_core.pyd` interface for `seed` or `random_state` kwargs in `__init__` or `reset()`.

3. **Noise-Robust Evaluation (Priority: MEDIUM)**
   If match execution is inherently non-deterministic, adopt noise-robust evaluation:
   - Run each candidate 3–5× per opponent and use median score
   - Use CMA-ES noise-handling options (`'noise_handling': True`)
   - This converts non-determinism from a bug into a managed variance source

4. **Cross-Run Regression Test (Priority: MEDIUM)**
   Store a reference optimization trajectory (seed=42, budget=50) with expected fitness values at each generation. Re-run periodically and assert fitness values match within tolerance.

5. **Fix Unseeded LHS in bt_optimizer.py (Priority: LOW)**
   Ensure all `latin_hypercube_sample()` calls receive an explicit seeded RNG to prevent accidental non-determinism in auxiliary code paths.

## 9. Pipeline Reliability — CMA-ES Convergence Guarantees

### 9.1 Budget-to-Dimension Ratio Analysis

The optimizer searches a **104-dimensional** space with a default budget of **400 evaluations**.

| Metric | Value | Assessment |
|--------|-------|------------|
| **Dimensions (N)** | 104 | 8 binary structural + 9 discrete slot selections + ~83 continuous/discrete node params + 4 global params |
| **Budget (B)** | 400 | Default `--budget 400` in CLI |
| **Ratio B/N** | 3.85 | **Critically low** |
| **Population size** | `min(n_workers * 2, 40)` | Typically 8–40 depending on CPU count |
| **Generations** | ~10–50 | Budget / popsize = 400/40 = 10 generations at max popsize |
| **Effective continuous dims** | ~87 | Continuous params where CMA-ES covariance adaptation applies |
| **Effective discrete dims** | ~17 | Binary + categorical dims encoded as continuous (degrade covariance learning) |

**CMA-ES rule of thumb:** For reliable convergence on unimodal functions, CMA-ES requires **~10×N² / popsize** evaluations to fully adapt the covariance matrix (Hansen 2016). For N=104:

- **Full covariance adaptation:** ~10 × 104² / 40 = **27,040 evaluations**
- **Minimum for meaningful progress:** ~10×N = **1,040 evaluations**
- **Current budget:** 400 — **2.6× below even the minimum threshold**

Even on a perfectly smooth unimodal landscape, 400 evaluations allow CMA-ES only ~10 generations — barely enough to estimate the gradient direction, let alone adapt the full 104×104 covariance matrix.

### 9.2 Convergence Theory Comparison

| CMA-ES Theory Requirement | Pipeline Status | Gap |
|---------------------------|----------------|-----|
| **Sufficient budget for covariance learning** (O(N²) evals) | 400 evals for N=104 | ❌ **~68× under-budget** for full adaptation |
| **Continuous search space** | Mixed: ~17 discrete dims encoded as continuous [0,1] → index | ⚠️ Discrete variables create discontinuous fitness landscape; covariance matrix wastes capacity modeling non-existent correlations between discrete choices |
| **Bounded noise or noise handling** | Single-round evaluation per opponent (1 match each vs 40 opponents) | ❌ **No noise handling**. `tolfun: 1e-6` termination criterion is meaningless when evaluation noise >> 1e-6. CMA-ES `noise_handling` option is not enabled |
| **Multiple restarts for multimodal landscapes** | No restarts implemented | ❌ Single run from one initial point |
| **Population diversity maintenance** | Standard CMA-ES (no BIPOP, no IPOP) | ❌ No diversity mechanism |
| **Convergence monitoring** | No sigma/eigenvalue tracking, no stagnation detection | ❌ Pipeline does not check whether optimizer actually converged |

**Key theory result (Hansen & Auger, 2014):** CMA-ES with default settings converges on separable functions in O(N) evaluations and on ill-conditioned functions in O(N²) evaluations. However, this assumes:
1. A continuous, at least piecewise-smooth objective
2. Sufficient budget to run to termination
3. Unimodal basin of attraction (or restarts for multimodal)

The pipeline violates all three assumptions: (1) discrete parameters create a discontinuous landscape, (2) budget is 400 vs. the ~27,000 needed, (3) no restarts are used.

### 9.3 Multi-Start / Restart Assessment

**Current implementation:** `run_search()` performs a **single CMA-ES run** from one starting point.

| Restart Strategy | Present? | Impact |
|-----------------|----------|--------|
| **IPOP-CMA-ES** (increasing population restarts) | ❌ No | Cannot escape local optima; population size is fixed |
| **BIPOP-CMA-ES** (bi-population restarts) | ❌ No | No alternation between large-pop global search and small-pop local refinement |
| **Random restarts** | ❌ No | Single x0 = default params (line 556) |
| **Multi-start from diverse seeds** | ❌ No | CLI supports `--seed` but pipeline runs once |
| **Warm-starting from previous best** | ❌ No | Each run is independent; no incremental improvement across sessions |

The starting point `x0` is always the default/builtin parameter vector (line 556: `x0 = params_to_vector(defaults)`). With σ₀=0.3, the initial search distribution covers roughly ±0.3 in each dimension (i.e., ±30% of each parameter range). Regions of the search space far from the default configuration are unlikely to be explored within 10 generations.

### 9.4 Multimodality of the Fitness Landscape

The fitness landscape is almost certainly **highly multimodal** for several reasons:

1. **Discrete structural choices:** The 9 action slots create ~2×3×6×3×5×4×3×5×3 = **97,200 discrete structural configurations**. Each configuration defines a different BT topology with its own local optimum for continuous parameters.

2. **Opponent-dependent fitness:** Score is aggregated over 40 opponents. A configuration that excels against offensive opponents may fail against defensive ones, creating many Pareto-like optima.

3. **Branch enable/disable:** The 8 binary enable flags create 2⁸ = **256 structural modes**, each with potentially different optimal continuous parameters.

4. **Non-smooth interactions:** Enabling `enable_underfire` changes the BT's priority ordering, which can discontinuously alter behavior against certain opponents.

With 400 evaluations, the optimizer explores at most 400 of the ~97,200 discrete configurations × continuous parameter space — a vanishingly small fraction.

### 9.5 Convergence Verification: Does the Pipeline Test for Convergence?

**Answer: No.** The pipeline has no convergence diagnostics.

| Convergence Indicator | Checked? | Details |
|-----------------------|----------|---------|
| **CMA-ES sigma (step size)** | ❌ | Not logged or monitored. If sigma collapses, search has converged (locally). If sigma remains large, search has not converged. |
| **Best fitness plateau** | ❌ | Best score is tracked (`best_score`) but no stagnation detection |
| **Eigenvalue ratio** (condition number) | ❌ | Not monitored. High condition number indicates search is elongated along certain axes |
| **`es.stop()` termination reasons** | ❌ | CMA-ES returns stop conditions but they are not logged or reported |
| **Generation-over-generation improvement** | ❌ | Not tracked; loop simply runs until budget exhaustion |
| **Post-optimization convergence report** | ❌ | Only prints best score and saves top-20 results |

The `while not es.stop() and total_evals < budget` loop (line 580) will almost always terminate by **budget exhaustion** rather than CMA-ES convergence criteria, because the budget is far too small for the optimizer to reach its internal convergence thresholds.

### 9.6 Mitigating Factors

Despite the severe theoretical limitations, two design decisions partially compensate:

1. **Intelligent initialization (x0 = defaults):** Starting from the hand-tuned default parameters means the optimizer begins in a "known good" region. Even with only 10 generations of local refinement, it can improve upon the baseline. The plan document's claim that "결과 ≥ 빌트인 보장" (result ≥ builtin guarantee) is **theoretically correct** — the default is in the search space — but **practically unreliable** because noisy evaluation can cause CMA-ES to accept a worse configuration.

2. **Full-pool validation:** The `validate_on_full_pool()` function (695 opponents × 10 rounds = 6,950 matches) provides a rigorous post-hoc check. Even if the optimizer finds a suboptimal solution, the validation step can detect poor performance with CI ≈ ±1.18%.

### 9.7 Verdict: Can the Pipeline Guarantee Finding the Global Optimum?

**No. The pipeline cannot guarantee finding the global optimum, nor can it guarantee finding a near-optimal solution.**

**Evidence:**

| Factor | Status | Severity |
|--------|--------|----------|
| Budget/dimension ratio of 3.85 | 68× below full covariance adaptation | 🔴 Critical |
| No restarts on a multimodal landscape | ~97,200 discrete modes unexplored | 🔴 Critical |
| Mixed discrete-continuous space | Degrades CMA-ES covariance learning | 🟠 High |
| Noisy single-round evaluation | Fitness noise >> convergence tolerance | 🟠 High |
| No convergence monitoring | Cannot distinguish converged vs. budget-exhausted | 🟡 Medium |
| Good initialization from defaults | Enables local refinement near baseline | 🟢 Mitigating |
| Full-pool validation safety net | Catches poor solutions post-hoc | 🟢 Mitigating |

**Conclusion:** A better BT almost certainly exists undiscovered. The optimizer performs **local refinement around the default configuration** rather than global optimization. The pipeline is best understood as "automated parameter tuning near a hand-designed baseline" rather than "global search for the best possible BT." To approach global optimality, the pipeline would need:

1. **Budget increase:** 5,000–10,000+ evaluations (currently 400)
2. **BIPOP/IPOP restarts:** Automatic restarts with increasing population sizes
3. **Noise-robust evaluation:** 3–5 rounds per opponent per candidate, or CMA-ES `noise_handling=True`
4. **Discrete-continuous decomposition:** Separate optimizer for structural choices (e.g., grid search or evolutionary strategy over discrete slots) with CMA-ES for continuous params within each structure
5. **Convergence logging:** Track sigma, eigenvalues, and `es.stop()` reasons to know when optimization has actually converged vs. simply exhausted its budget

## 10. Pipeline Reliability — Regression Risk & Version Tracking

### 10.1 Version History Regression Analysis

The version history in `ADAPTIVE_BT_PLAN.md` Appendix A documents 11 versions (v3.x through v6.0/v4.7). Analyzing win rate trajectory reveals a critical regression incident and unstable progression:

| Version | Win Rate | Δ from Previous | Classification |
|---------|----------|-----------------|----------------|
| v3.x | ~50% | — | Baseline |
| v4.0–v4.3 | Unstable | — | Integration failures (no measurement) |
| **v4.4** | **0%** | **−50%** | 🔴 **CATASTROPHIC REGRESSION** |
| v4.5 | 57% | +57% | Recovery (reverted approach) |
| v4.6 | 38–80% | Variable | Non-deterministic (drift bug) |
| v5.0 | 50% | −7% to +12% | Bug fixes, measurement stabilized |
| v5.0-smart | 30% | −20% | 🟠 **SIGNIFICANT REGRESSION** |
| v5.1 | 60% | +30% | Recovery (reverted heading approach) |
| v6.0 | 70% (stratified) | +10% | Current best |

**Key regression incidents:**

1. **v4.4 (57% → 0%):** `RLInspiredAttack` node had a left-right inversion bug. The agent literally flew in the wrong direction. This regression was **not caught by any automated test** — it was discovered through manual match observation. The version note explicitly states "회귀 테스트 필요" (regression test needed), acknowledging the gap.

2. **v5.0-smart (60% → 30%):** `SmartLeadPursuit` custom heading logic performed worse than the builtin proportional navigation. This regression was caught by `evaluate.py` measurement after deployment, not before. The lesson ("heading은 빌트인이 우수" — builtin heading is superior) was learned through post-hoc measurement rather than pre-commit validation.

3. **v4.6 (38–80% variance):** Online drift caused win rate to swing wildly between runs. This was a **reproducibility regression** — the same agent produced fundamentally different results across runs. No determinism test existed to flag this.

**Pattern:** Every regression was discovered **after deployment**, through manual evaluation or observation. No regression was caught by an automated gate before the change was committed.

### 10.2 Automated Regression Detection Assessment

**Does the pipeline have mechanisms to detect regressions automatically?**

**Answer: ❌ No automated regression detection exists.**

| Regression Detection Mechanism | Present? | Details |
|-------------------------------|----------|---------|
| **Pre-commit performance gate** (run eval before commit) | ❌ No | No CI/CD pipeline; no pre-commit hook that runs `evaluate.py` |
| **Baseline comparison** (new version ≥ previous version) | ❌ No | No stored baseline win rate to compare against |
| **Automated A/B testing** (new vs old on same opponent pool) | ❌ No | No harness for side-by-side comparison |
| **Determinism regression test** (same inputs → same outputs) | ❌ No | No recorded reference trajectories; DRIFT bug (v4.6) went undetected |
| **Structural regression** (BT validity after edit) | ⚠️ Partial | `test_suite.py` validates structure but not performance |
| **Win rate threshold gate** (WR must exceed X%) | ❌ No | No minimum performance threshold enforced |
| **Per-opponent tracking** (no opponent goes from win→loss) | ❌ No | No per-opponent historical tracking |
| **Version-to-version diff analysis** | ❌ No | `logs/cycle_N/diff_vs_prev.md` is planned (§4.4) but not implemented |

**What exists vs. what's needed:**

- **Exists:** `tools/evaluate.py` can measure win rate with Wilson CI. `tools/test_suite.py` validates structural correctness.
- **Missing:** Nothing connects these tools into an automated gate. A developer can introduce a v4.4-style catastrophic regression, commit it, and only discover it hours later through manual testing.
- **Planned but unimplemented:** `ADAPTIVE_BT_PLAN.md` §4.4 describes a `logs/cycle_N/` directory structure with `diff_vs_prev.md` for tracking version-to-version changes — but this infrastructure does not exist in the codebase.

### 10.3 Feedback Loop Automation Assessment

`ADAPTIVE_BT_PLAN.md` Section 4 defines a **feedback loop matrix** mapping symptoms to diagnoses to target phases:

| Matrix Feature | Automation Status | Assessment |
|---------------|-------------------|------------|
| **Symptom → Diagnosis mapping** (§4.1, 8 rows) | 📝 Manual | Written as human-readable table. No code implements `diagnose(validation_results) → target_phase` |
| **Phase-specific playbooks** (§4.2) | 📝 Manual | Written as prose instructions (e.g., "같은 BT를 k회 평가하여 분산 측정"). No automated executor |
| **Single-Phase-per-cycle rule** (§4.3) | 📝 Manual | Discipline constraint for human operators. No enforcement mechanism |
| **Cycle logging infrastructure** (§4.4) | 📝 Planned | `logs/cycle_N/{best.yaml, validation.json, diagnosis.md, changeset.md, diff_vs_prev.md}` — directory structure defined but not created by any script |
| **Automated diagnosis from validation results** | ❌ None | No code parses `validation.json` to identify "CI too wide" → Phase 1, or "L6 weak" → Phase 4 |
| **Automated phase selection** | ❌ None | Human must read validation results and manually decide which phase to reinforce |

**Diagnosis capability assessment:**

The feedback matrix (§4.1) identifies 8 symptom→diagnosis→phase mappings. To automate these, the pipeline would need:

| Symptom | Required Data | Available? | Automatable? |
|---------|--------------|------------|-------------|
| "CI too wide" | Per-opponent CI widths from `evaluate.py` | ✅ Yes | ✅ Trivial: `any(ci_width > threshold for ci in per_opponent_cis)` |
| "New best regresses vs previous" | Historical best WR | ❌ No stored history | ⚠️ Needs baseline storage |
| "Consistent loss to specific layer" | Per-layer WR from full-pool validation | ✅ Yes (in `validation.json`) | ✅ `min(layer_wr) < threshold` |
| "EIM ON weaker than OFF" | Ablation comparison (EIM on vs off) | ❌ Not automated | ⚠️ Needs ablation harness |
| "Saturation at 50%" | Overall WR plateau | ✅ Yes | ✅ `abs(wr - 0.5) < epsilon` |
| "CMA-ES premature convergence" | Sigma, eigenvalue tracking | ❌ Not logged | ❌ Needs optimizer instrumentation |
| "Good per-opp, low average" | Per-opponent variance vs mean | ✅ Yes | ✅ `std(per_opp_wr) > threshold` |
| "Weak to L6 counters" | L6-specific WR | ✅ Yes | ✅ `layer_wr['L6'] < threshold` |

**Summary:** 5 of 8 diagnoses **could be automated** with existing data sources (CI widths, per-layer WR, per-opponent WR from `evaluate.py`/`validation.json`). The remaining 3 require new data (historical baselines, ablation results, optimizer telemetry) that the pipeline does not currently collect.

### 10.4 Regression Risk Rating

| Risk Category | Rating | Justification |
|--------------|--------|---------------|
| **Catastrophic regression risk** (v4.4-style, WR→0%) | 🔴 **HIGH** | No automated performance gate. `test_suite.py` only checks structure, not behavior. A node with inverted logic passes all 5 structural checks. |
| **Silent regression risk** (5-10% WR drop) | 🔴 **HIGH** | No baseline comparison. Small regressions are invisible without explicit A/B evaluation, which is not automated. |
| **Reproducibility regression** (v4.6-style drift) | 🟠 **MEDIUM-HIGH** | No determinism test. DRIFT bug was fixed, but the same class of bug could recur in any match-level code change. |
| **Feedback loop effectiveness** | 🟠 **MEDIUM** | The diagnostic framework is well-designed on paper (§4.1 matrix is comprehensive), but 0% is automated. The pipeline relies entirely on human discipline to execute the feedback loop. |
| **Version tracking reliability** | 🟡 **MEDIUM** | Version history exists in `ADAPTIVE_BT_PLAN.md` Appendix A (manual), and CMA-ES outputs are saved to `logs/`. But no structured versioning system (no `cycle_N/` directories, no automated diff). |

**Overall Regression Risk: 🔴 HIGH**

The pipeline has **zero automated regression detection**. Every historical regression (v4.4 catastrophic, v5.0-smart performance drop, v4.6 drift instability) was discovered through manual observation after the fact. The feedback loop matrix (Section 4) provides an excellent diagnostic framework, but none of it is implemented as code. The gap between the plan's sophistication and the implementation's reality is the pipeline's single greatest reliability risk.
