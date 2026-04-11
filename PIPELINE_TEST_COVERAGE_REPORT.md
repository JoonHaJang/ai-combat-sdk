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
