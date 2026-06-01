"""
Match Core - 매치 실행 핵심 로직 (보호 대상)

이 모듈은 Cython으로 컴파일되어 SDK에 .pyd 형태로 배포됩니다.
"""

from pathlib import Path
from typing import Optional, Callable, Dict
import sys
import time
import numpy as np
from datetime import datetime, timezone, timedelta

from src.simulation.envs.JSBSim.envs import SingleCombatEnv
from src.simulation.envs.JSBSim.core.catalog import JsbsimCatalog as _prp
from ..behavior_tree.task import BehaviorTreeTask
from .result import MatchResult
from src.control.health_manager import HealthGauge
from .judge import MatchJudge, VictoryCondition
from ..utils.units import meters_to_feet
from .wez_engine import calculate_wez_damage
from .acmi_formatter import build_full_frame
from .replay_writer import ReplayWriter

KST = timezone(timedelta(hours=9))


def _print(msg: str):
    """Windows cp949 환경에서도 UTF-8로 안전하게 출력"""
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + '\n').encode('utf-8', errors='replace'))
        sys.stdout.buffer.flush()


class MatchCore:
    """매치 실행 핵심 로직"""

    def __init__(
        self,
        tree1_file: str,
        tree2_file: str,
        config_name: str = "1v1/NoWeapon/bt_vs_bt",
        max_steps: int = 1000,
        tree1_name: Optional[str] = None,
        tree2_name: Optional[str] = None,
        step_hook: Optional[Callable] = None,
        realtime_server=None,
        realtime_pacing: bool = False,
    ):
        """
        Args:
            tree1_file: 첫 번째 행동트리 YAML 파일
            tree2_file: 두 번째 행동트리 YAML 파일
            config_name: LAG 환경 설정 이름
            max_steps: 최대 스텝 수
            tree1_name: 첫 번째 에이전트 이름 (선택)
            tree2_name: 두 번째 에이전트 이름 (선택)
            step_hook: 매 스텝 후 runner.py에서 호출되는 내부 훅
                시그니처: hook(step, task1, task2, health1, health2,
                              action1, action2, reward1, reward2, debug_info, env)
            realtime_server: TacviewRealtimeServer 인스턴스 (None이면 실시간 중계 비활성)
            realtime_pacing: True이면 실시간 페이싱 적용 (dt=0.2s 간격)
        """
        self.tree1_file = tree1_file
        self.tree2_file = tree2_file
        self.config_name = config_name
        self.max_steps = max_steps
        self.tree1_name = tree1_name or Path(tree1_file).stem
        self.tree2_name = tree2_name or Path(tree2_file).stem
        self.step_hook = step_hook
        self.realtime_server = realtime_server
        self.realtime_pacing = realtime_pacing

        self.task1: Optional[BehaviorTreeTask] = None
        self.task2: Optional[BehaviorTreeTask] = None
        self.health1: Optional[HealthGauge] = None
        self.health2: Optional[HealthGauge] = None
        self._last_wez_debug: Optional[Dict] = None

    def run(
        self,
        replay_path: Optional[str] = None,
        verbose: bool = False,
    ) -> MatchResult:
        """매치 실행"""
        start_time = datetime.now(KST)
        # ACMI ReferenceTime: 오늘 날짜 UTC 12:00:00 고정
        # Tacview에서 #0.0 = 12:00:00.000 → 경과시간 = 표시시간 - 12:00:00
        _today_utc = datetime.now(timezone.utc).date()
        _acmi_ref = datetime(_today_utc.year, _today_utc.month, _today_utc.day,
                             12, 0, 0, tzinfo=timezone.utc)

        env = SingleCombatEnv(self.config_name)
        tree1_name = self.tree1_name
        tree2_name = self.tree2_name

        env.tree1_name = tree1_name
        env.tree2_name = tree2_name

        # max_steps=0이면 5분(300초)을 env.time_interval로 나눠 동적 계산.
        # Hz 변경에 무관하게 항상 동일한 실제 경기 시간을 보장.
        _MAX_DURATION_SEC = 300.0
        if self.max_steps <= 0:
            self.max_steps = max(1, int(round(_MAX_DURATION_SEC / float(env.time_interval))))
        env.config.max_steps = self.max_steps
        self.task1 = BehaviorTreeTask(env.config, tree_file=self.tree1_file)
        self.task2 = BehaviorTreeTask(env.config, tree_file=self.tree2_file)
        task1 = self.task1
        task2 = self.task2

        self.health1 = HealthGauge(initial_health=100.0)
        self.health2 = HealthGauge(initial_health=100.0)
        health1 = self.health1
        health2 = self.health2

        judge = MatchJudge(max_steps=self.max_steps)

        if verbose:
            print("매치 시작:")
            print(f"  Tree 1: {Path(self.tree1_file).name} -> ego_id={env.ego_ids[0]}")
            print(f"  Tree 2: {Path(self.tree2_file).name} -> enm_id={env.enm_ids[0]}")
            print(f"  Config: {self.config_name}")
            print(f"  Max steps: {self.max_steps}")
            print(f"  Health: {health1.current_health} HP each")

        obs = env.reset()

        # 실시간 텔레메트리 매치 시작
        if self.realtime_server is not None:
            self.realtime_server.start_match(
                title=f"BT Match: {tree1_name} vs {tree2_name}",
                blue_id=env.ego_ids[0],
                red_id=env.enm_ids[0],
                blue_name=tree1_name,
                red_name=tree2_name,
            )

        replay_writer = None
        if replay_path:
            replay_path = Path(replay_path)
            if replay_path.exists():
                replay_path.unlink()
            with open(replay_path, 'w', encoding='utf-8-sig') as f:
                f.write("FileType=text/acmi/tacview\n")
                f.write("FileVersion=2.2\n")
                f.write("0,Author=AI-Combat Platform\n")
                f.write(f"0,Title=Behavior Tree Match: {tree1_name} vs {tree2_name}\n")
                f.write(f"0,ReferenceTime={_acmi_ref.strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
                f.write(f"0,Comments=Tree1={tree1_name}, Tree2={tree2_name}\n")
                f.write("0,Category=AI Dogfight\n")
                f.write("#0.0\n")
                ego_uid = env.ego_ids[0]
                enm_uid = env.enm_ids[0]
                f.write(f"{ego_uid},Type=Air+FixedWing,Name=F-16,Pilot={tree1_name},Color=Blue\n")
                f.write(f"{enm_uid},Type=Air+FixedWing,Name=F-16,Pilot={tree2_name},Color=Red\n")
            env._create_records = True  # env.render() 헤더 덮어쓰기 방지
            replay_writer = ReplayWriter(str(replay_path))
            replay_writer.start()

        _replay_prev_nodes: Dict[str, str] = {}
        total_reward_1 = 0.0
        total_reward_2 = 0.0
        step_count = 0
        done = False
        winner = None
        victory_condition = None
        next_step_time = time.perf_counter() if self.realtime_pacing else 0

        # BT 10 Hz 분리: env.step rate(20 Hz)와 무관하게 BT 결정은 100 ms 간격.
        # env.time_interval에서 동적 산출 → 향후 step rate 변경에도 자동 정합.
        # RNN(저수준 정책) 5 Hz 캐시는 HierarchicalSingleCombatTask.normalize_action에서 처리.
        BT_TICK_EVERY = max(1, round(0.1 / float(env.time_interval)))
        bt_tick_counter = BT_TICK_EVERY  # 첫 스텝에서 즉시 BT tick 실행
        action1 = None
        action2 = None

        while not done and step_count < self.max_steps:
            if bt_tick_counter >= BT_TICK_EVERY:
                bt_tick_counter = 0
                action1 = task1.get_high_level_action(env, env.ego_ids[0])
                action2 = task2.get_high_level_action(env, env.enm_ids[0])
            bt_tick_counter += 1

            action = np.array([action1, action2])
            obs, reward, dones, info = env.step(action)

            # env.task._lowlevel_action_cache → task1/task2 동기화
            # env.step은 env.task.normalize_action만 호출하므로
            # 별도 BehaviorTreeTask 객체의 _last_low_level_action은 자동 갱신되지 않음.
            _ll_cache = getattr(env.task, '_lowlevel_action_cache', {})
            for _tsk, _aid in [(task1, env.ego_ids[0]), (task2, env.enm_ids[0])]:
                if _aid in _ll_cache:
                    _na = _ll_cache[_aid]
                    _tsk._last_low_level_action = {
                        "aileron": float(_na[0]),
                        "elevator": float(_na[1]),
                        "rudder": float(_na[2]),
                        "throttle": float(_na[3]),
                    }

            # 20 Hz condition subtick: blackboard 갱신(/Distance_ft, PS, BFM 등) +
            # BaseCondition.update() 호출. 액션 노드와 TimedAction 카운터는 영향 없음.
            try:
                task1.tick_conditions(env, env.ego_ids[0])
                task2.tick_conditions(env, env.enm_ids[0])
            except Exception as _tc_err:
                print(f"[MatchCore] tick_conditions error step={step_count}: {_tc_err}")

            control_inputs = {}
            prp = _prp
            for agent_id in [env.ego_ids[0], env.enm_ids[0]]:
                agent = env.agents[agent_id]
                try:
                    aileron_cmd = agent.get_property_value(prp.fcs_aileron_cmd_norm)
                    elevator_cmd = agent.get_property_value(prp.fcs_elevator_cmd_norm)
                    rudder_cmd = agent.get_property_value(prp.fcs_rudder_cmd_norm)
                    throttle_cmd = agent.get_property_value(prp.fcs_throttle_cmd_norm)
                    control_inputs[agent_id] = [aileron_cmd, elevator_cmd, rudder_cmd, throttle_cmd]
                except (AttributeError, KeyError, ValueError, TypeError):
                    control_inputs[agent_id] = [0.0, 0.0, 0.0, 0.5]

            dt = env.time_interval
            damage1, damage2, debug_info = self._calculate_wez_damage(env, dt)
            self._last_wez_debug = debug_info

            if verbose and step_count % 50 == 0 and debug_info:
                if 'error' in debug_info:
                    print(f"  [WEZ] Error: {debug_info['error']}")
                else:
                    print(f"  [WEZ] dist={meters_to_feet(debug_info['distance']):.0f}ft, "
                          f"ata1={debug_info['ata1']:.1f}, ata2={debug_info['ata2']:.1f}, "
                          f"dmg1={damage1:.2f}, dmg2={damage2:.2f}")

            if damage1 > 0:
                health1.take_damage(damage1, step_count)
                health2.deal_damage(damage1)
                if replay_writer:
                    replay_writer.write(f"0,Event=Bookmark|{env.enm_ids[0]}|[Red] HIT! {damage1:.2f} HP\n")
            if damage2 > 0:
                health2.take_damage(damage2, step_count)
                health1.deal_damage(damage2)
                if replay_writer:
                    replay_writer.write(f"0,Event=Bookmark|{env.ego_ids[0]}|[Blue] HIT! {damage2:.2f} HP\n")

            if not health1.is_alive() and not health2.is_alive():
                winner = "draw"
                victory_condition = VictoryCondition.TIMEOUT
                done = True
            elif not health1.is_alive():
                winner = "tree2"
                victory_condition = VictoryCondition.HEALTH_ZERO
                done = True
            elif not health2.is_alive():
                winner = "tree1"
                victory_condition = VictoryCondition.HEALTH_ZERO
                done = True

            if not done:
                try:
                    _ego_pos = env.agents[env.ego_ids[0]].get_position()
                    _enm_pos = env.agents[env.enm_ids[0]].get_position()
                    _alt1_m = float(_ego_pos[2])
                    _alt2_m = float(_enm_pos[2])
                    _j_winner, _j_cond = judge.judge(
                        health1.current_health, health2.current_health,
                        _alt1_m, _alt2_m, step_count
                    )
                    if _j_winner is not None and _j_cond == VictoryCondition.HARD_DECK_VIOLATION:
                        winner = "tree1" if _j_winner == "agent1" else "tree2"
                        victory_condition = _j_cond
                        done = True
                        if replay_writer:
                            _viol_uid = env.enm_ids[0] if winner == "tree1" else env.ego_ids[0]
                            replay_writer.write(f"0,Event=Bookmark|{_viol_uid}|[Hard Deck] 고도 위반 — {winner} 승리\n")
                except (AttributeError, KeyError, ValueError, TypeError):
                    pass

            reward1 = 0.0
            reward2 = 0.0
            if isinstance(reward, np.ndarray):
                if reward.ndim == 2 and reward.shape[0] >= 2:
                    reward1 = float(reward[0, 0])
                    reward2 = float(reward[1, 0])
                elif reward.ndim == 1 and len(reward) >= 2:
                    reward1 = float(reward[0])
                    reward2 = float(reward[1])
                else:
                    reward1 = float(reward.flatten()[0]) if reward.size > 0 else 0.0
            else:
                reward1 = float(reward)

            _in_wez1 = debug_info.get('in_wez1', False) if debug_info and 'in_wez1' in debug_info else False
            _in_wez2 = debug_info.get('in_wez2', False) if debug_info and 'in_wez2' in debug_info else False
            _inject1 = getattr(task1, 'inject_match_state', None)
            if _inject1:
                _inject1(
                    ego_health=health1.current_health,
                    enm_health=health2.current_health,
                    ego_damage_dealt=health1.total_damage_dealt,
                    enm_damage_dealt=health2.total_damage_dealt,
                    ego_damage_received=health2.total_damage_dealt,
                    enm_damage_received=health1.total_damage_dealt,
                    in_wez=_in_wez1,
                    enm_in_wez=_in_wez2,
                    reward=reward1,
                )
            _inject2 = getattr(task2, 'inject_match_state', None)
            if _inject2:
                _inject2(
                    ego_health=health2.current_health,
                    enm_health=health1.current_health,
                    ego_damage_dealt=health2.total_damage_dealt,
                    enm_damage_dealt=health1.total_damage_dealt,
                    ego_damage_received=health1.total_damage_dealt,
                    enm_damage_received=health2.total_damage_dealt,
                    in_wez=_in_wez2,
                    enm_in_wez=_in_wez1,
                    reward=reward2,
                )

            # step_hook: runner.py의 CSV/콜백 레이어가 주입하는 훅
            if self.step_hook is not None:
                try:
                    self.step_hook(
                        step=step_count,
                        task1=task1,
                        task2=task2,
                        health1=health1,
                        health2=health2,
                        action1=action1,
                        action2=action2,
                        reward1=reward1,
                        reward2=reward2,
                        debug_info=debug_info,
                        env=env,
                    )
                except Exception as _hook_err:
                    print(f"[MatchCore] step_hook error step={step_count}: {_hook_err}")

            # ── BT 노드 정보 수집 (파일 + 실시간 공용) ──
            _bt_info: Dict[str, dict] = {}
            for _aid, _tsk, _tname, _clr in [
                (env.ego_ids[0], task1, tree1_name, 'Blue'),
                (env.enm_ids[0], task2, tree2_name, 'Red'),
            ]:
                _node_info: dict = {
                    'color': _clr, 'tree_name': _tname,
                    'active_node': '', 'node_path': '',
                }
                if hasattr(_tsk, 'get_last_active_nodes'):
                    _active = _tsk.get_last_active_nodes()
                    if _active:
                        _an = [n for n, s in _active if s == 'SUCCESS']
                        if _an:
                            _node_info['active_node'] = _an[-1]
                            _node_info['node_path'] = ">".join([n for n, s in _active])
                _bt_info[_aid] = _node_info

            _health_map = {
                env.ego_ids[0]: health1.current_health,
                env.enm_ids[0]: health2.current_health,
            }
            _reward_map = {env.ego_ids[0]: reward1, env.enm_ids[0]: reward2}

            # ── 프레임 공통 생성 (리플레이 & 실시간 텔레메트리) ──
            _frame = None
            if replay_writer or self.realtime_server is not None:
                try:
                    _frame = build_full_frame(
                        env=env,
                        sim_time=(step_count + 1) * env.time_interval,
                        control_inputs=control_inputs,
                        wez_debug=self._last_wez_debug,
                        health_map=_health_map,
                        reward_map=_reward_map,
                        bt_info=_bt_info,
                        step_count=step_count,
                        max_steps=self.max_steps,
                        use_extended_log=True,
                        prev_node_map=_replay_prev_nodes,
                    )
                except Exception:
                    pass

            # ── Tacview 리플레이 기록 (비동기, build_full_frame 사용) ──
            if replay_writer and _frame:
                try:
                    replay_writer.write(_frame)
                except Exception:
                    pass

            # ── 실시간 텔레메트리 프레임 전송 ──
            if self.realtime_server is not None and _frame:
                try:
                    self.realtime_server.send_frame(_frame)
                except Exception:
                    pass

            total_reward_1 += reward1
            total_reward_2 += reward2
            step_count += 1
            if not done:
                done = dones.any() if isinstance(dones, np.ndarray) else dones

            if verbose and step_count % 50 == 0:
                print(f"  Step {step_count}: reward={reward}")

            # 실시간 페이싱
            if self.realtime_pacing:
                next_step_time += env.time_interval
                sleep_time = next_step_time - time.perf_counter()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                elif sleep_time < -0.05:
                    next_step_time = time.perf_counter()

        if replay_writer:
            replay_writer.stop()
        env.close()

        # 실시간 텔레메트리 매치 종료
        if self.realtime_server is not None:
            winner_display = tree1_name if winner == "tree1" else tree2_name if winner == "tree2" else "무승부"
            self.realtime_server.end_match(winner=winner_display)

        if winner is None:
            if health1.current_health > health2.current_health:
                winner = "tree1"
                victory_condition = VictoryCondition.HEALTH_ADVANTAGE
            elif health2.current_health > health1.current_health:
                winner = "tree2"
                victory_condition = VictoryCondition.HEALTH_ADVANTAGE
            else:
                winner = "draw"
                victory_condition = VictoryCondition.TIMEOUT

        end_time = datetime.now(KST)
        duration = (end_time - start_time).total_seconds()

        result = MatchResult(
            tree1_file=self.tree1_file,
            tree2_file=self.tree2_file,
            winner=winner,
            total_steps=step_count,
            tree1_reward=float(total_reward_1),
            tree2_reward=float(total_reward_2),
            replay_file=str(replay_path) if replay_path else None,
            duration_seconds=duration,
            timestamp=start_time.isoformat(),
        )
        result.tree1_health = health1.current_health
        result.tree2_health = health2.current_health
        result.tree1_damage_dealt = health1.total_damage_dealt
        result.tree2_damage_dealt = health2.total_damage_dealt
        result.victory_condition = victory_condition.value if victory_condition else VictoryCondition.TIMEOUT.value

        winner_display = tree1_name if winner == "tree1" else tree2_name if winner == "tree2" else "무승부"
        _print("\n매치 완료:")
        _print(f"  승자: {winner_display} [{result.victory_condition}]")
        _print(f"  스텝: {step_count} / {self.max_steps}")
        _print(f"  소요 시간: {duration:.2f}초")
        _print(f"  {tree1_name}: {health1.current_health:.1f} HP")
        _print(f"  {tree2_name}: {health2.current_health:.1f} HP")

        return result

    def _calculate_wez_damage(self, env, dt: float) -> tuple:
        """Gun WEZ 체크 및 데미지 계산 (wez_engine 위임)"""
        try:
            ego_sim = env.agents[env.ego_ids[0]]
            enm_sim = env.agents[env.enm_ids[0]]

            ep = ego_sim.get_position()
            np_ = enm_sim.get_position()
            ev = ego_sim.get_velocity()
            nv = enm_sim.get_velocity()

            result = calculate_wez_damage(
                ego_pos=[ep[0], ep[1], -ep[2]],
                enm_pos=[np_[0], np_[1], -np_[2]],
                ego_vel=[ev[0], ev[1], -ev[2]],
                enm_vel=[nv[0], nv[1], -nv[2]],
                ego_roll=float(ego_sim.get_rpy()[0]),
                enm_roll=float(enm_sim.get_rpy()[0]),
                dt=float(dt),
            )
            return result['damage1'], result['damage2'], result
        except (AttributeError, KeyError, ValueError, TypeError) as e:
            return 0.0, 0.0, {'error': str(e)}
