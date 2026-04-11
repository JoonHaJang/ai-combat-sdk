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

### Testability Classification Summary

| Classification | Count | Files |
|---------------|-------|-------|
| **Direct** (pure logic, testable with mocks/synthetic data) | 12 | evaluate, test_suite, generate_opponent_pool, metadata_logger, analyze_metadata, test_agent, opponent_classifier, counter_strategy_builder, distill_lag_dt, expand_archetypes, generate_agents, validate_agent |
| **Indirect** (requires sim environment, external models, or large data) | 7 | adaptive_optimizer, collect_phase1, bt_optimizer, bt_optimizer_v3, collect_gun, query_lag_policy, train_intent_model |
| **Config** (interactive/external service dependency, minimal testable logic) | 2 | test_dogfight2_connection, test_intent_live |

### Current Test Coverage Status

**No dedicated test files exist for any tools/ module.** There is no `tests/` directory in the project root. The only test-like files are `tools/test_suite.py` (a validation tool, not a unit test), `tools/test_agent.py` (a CLI runner, not a unit test), and `tools/test_intent_live.py` (a live verification script).
