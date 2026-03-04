"""
Match Core - 매치 실행 핵심 로직 (보호 대상)

이 모듈은 Cython으로 컴파일되어 SDK에 .pyd 형태로 배포됩니다.
"""

from pathlib import Path
from typing import Optional, Callable, Dict
import sys
import numpy as np
from datetime import datetime, timezone, timedelta

from src.simulation.envs.JSBSim.envs import SingleCombatEnv
from src.simulation.envs.JSBSim.core.catalog import JsbsimCatalog as _prp
from src.simulation.envs.JSBSim.utils.utils import LLA2NEU
from ..behavior_tree.task import BehaviorTreeTask
from .result import MatchResult
from src.control.health_manager import HealthGauge
from ..control.combat_geometry import CombatGeometry
from .judge import MatchJudge, VictoryCondition
from ..utils.units import meters_to_feet, ms_to_knots
from .wez_engine import calculate_wez_damage

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
        """
        self.tree1_file = tree1_file
        self.tree2_file = tree2_file
        self.config_name = config_name
        self.max_steps = max_steps
        self.tree1_name = tree1_name or Path(tree1_file).stem
        self.tree2_name = tree2_name or Path(tree2_file).stem
        self.step_hook = step_hook

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

        env = SingleCombatEnv(self.config_name)
        tree1_name = self.tree1_name
        tree2_name = self.tree2_name

        env.tree1_name = tree1_name
        env.tree2_name = tree2_name

        self.task1 = BehaviorTreeTask(env.config, tree_file=self.tree1_file)
        self.task2 = BehaviorTreeTask(env.config, tree_file=self.tree2_file)
        task1 = self.task1
        task2 = self.task2

        self.health1 = HealthGauge(initial_health=100.0)
        self.health2 = HealthGauge(initial_health=100.0)
        health1 = self.health1
        health2 = self.health2

        _ = MatchJudge(max_steps=self.max_steps)

        if verbose:
            print("매치 시작:")
            print(f"  Tree 1: {Path(self.tree1_file).name} -> ego_id={env.ego_ids[0]}")
            print(f"  Tree 2: {Path(self.tree2_file).name} -> enm_id={env.enm_ids[0]}")
            print(f"  Config: {self.config_name}")
            print(f"  Max steps: {self.max_steps}")
            print(f"  Health: {health1.current_health} HP each")

        obs = env.reset()

        if replay_path:
            replay_path = Path(replay_path)
            if replay_path.exists():
                replay_path.unlink()
            with open(replay_path, 'w', encoding='utf-8-sig') as f:
                f.write("FileType=text/acmi/tacview\n")
                f.write("FileVersion=2.2\n")
                f.write("0,Author=AI-Combat Platform\n")
                f.write(f"0,Title=Behavior Tree Match: {tree1_name} vs {tree2_name}\n")
                f.write(f"0,ReferenceTime={start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
                f.write(f"0,Comments=Tree1={tree1_name}, Tree2={tree2_name}\n")
                f.write("0,Category=AI Dogfight\n")
                f.write("#0.0\n")
                ego_uid = env.ego_ids[0]
                enm_uid = env.enm_ids[0]
                f.write(f"{ego_uid},Type=Air+FixedWing,Name=F-16,Pilot={tree1_name},Color=Blue\n")
                f.write(f"{enm_uid},Type=Air+FixedWing,Name=F-16,Pilot={tree2_name},Color=Red\n")

        total_reward_1 = 0.0
        total_reward_2 = 0.0
        step_count = 0
        done = False
        winner = None
        victory_condition = None

        while not done and step_count < self.max_steps:
            action1 = task1.get_high_level_action(env, env.ego_ids[0])
            action2 = task2.get_high_level_action(env, env.enm_ids[0])

            action = np.array([action1, action2])
            obs, reward, dones, info = env.step(action)

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
                if replay_path:
                    with open(replay_path, "a") as f:
                        f.write(f"0,Event=Bookmark|{env.enm_ids[0]}|[Red] HIT! {damage1:.2f} HP\n")
            if damage2 > 0:
                health2.take_damage(damage2, step_count)
                health1.deal_damage(damage2)
                if replay_path:
                    with open(replay_path, "a") as f:
                        f.write(f"0,Event=Bookmark|{env.ego_ids[0]}|[Blue] HIT! {damage2:.2f} HP\n")

            if not health1.is_alive():
                winner = "tree2"
                victory_condition = VictoryCondition.HEALTH_ZERO
                done = True
            elif not health2.is_alive():
                winner = "tree1"
                victory_condition = VictoryCondition.HEALTH_ZERO
                done = True

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

            if replay_path:
                env.render(mode="txt", filepath=str(replay_path))
                try:
                    with open(replay_path, 'a', encoding='utf-8-sig') as f:
                        for i, agent_id in enumerate(env.agents.keys()):
                            agent = env.agents[agent_id]
                            enemy = agent.enemies[0] if agent.enemies else None
                            if enemy is None:
                                continue
                            ego_obs = np.array(agent.get_property_values(env.task.state_var))
                            enm_obs = np.array(enemy.get_property_values(env.task.state_var))
                            if len(ego_obs) < 12 or len(enm_obs) < 12:
                                continue
                            ego_ned = LLA2NEU(*ego_obs[:3], env.center_lon, env.center_lat, env.center_alt)
                            enm_ned = LLA2NEU(*enm_obs[:3], env.center_lon, env.center_lat, env.center_alt)
                            ego_vel_neu = agent.get_velocity()
                            enm_vel_neu = enemy.get_velocity()
                            ego_vel = np.array([ego_vel_neu[0], ego_vel_neu[1], -ego_vel_neu[2]])
                            enm_vel = np.array([enm_vel_neu[0], enm_vel_neu[1], -enm_vel_neu[2]])
                            ego_roll = agent.get_rpy()[0]
                            combat_geo = CombatGeometry(ego_ned, enm_ned, ego_vel, enm_vel, ego_roll)
                            params = combat_geo.get_all_params()
                            agent_reward = 0.0
                            if isinstance(reward, np.ndarray):
                                if reward.ndim == 2 and reward.shape[0] > i:
                                    agent_reward = reward[i, 0]
                                elif reward.ndim == 1 and len(reward) > i:
                                    agent_reward = reward[i]
                            if control_inputs and agent_id in control_inputs:
                                cmd_values = control_inputs[agent_id]
                                aileron = cmd_values[0] if cmd_values[0] is not None else 0.0
                                elevator = cmd_values[1] if cmd_values[1] is not None else 0.0
                                rudder = cmd_values[2] if cmd_values[2] is not None else 0.0
                                throttle = cmd_values[3] if cmd_values[3] is not None else 0.5
                            else:
                                aileron = elevator = rudder = 0.0
                                throttle = 0.5
                            try:
                                roll_pos = agent.get_property_value(prp.fcs_left_aileron_pos_norm)
                                pitch_pos = agent.get_property_value(prp.fcs_elevator_pos_norm)
                                yaw_pos = agent.get_property_value(prp.fcs_rudder_pos_norm)
                                if roll_pos is None or pitch_pos is None or yaw_pos is None:
                                    roll_pos = pitch_pos = yaw_pos = 0.0
                            except Exception:
                                roll_pos = pitch_pos = yaw_pos = 0.0
                            uid = agent.uid
                            f.write(f"{uid},RollControlInput={aileron:.2f},PitchControlInput={elevator:.2f},YawControlInput={rudder:.2f},Throttle={throttle:.2f}\n")
                            f.write(f"{uid},RollControlPosition={roll_pos:.4f},PitchControlPosition={pitch_pos:.4f},YawControlPosition={yaw_pos:.4f}\n")
                            f.write(f"{uid},StepsElapsed={step_count}/{self.max_steps}\n")
                            wez_debug = self._last_wez_debug
                            if wez_debug and 'distance' in wez_debug:
                                wez_ata = wez_debug['ata1'] if i == 0 else wez_debug['ata2']
                                distance_ft = meters_to_feet(wez_debug['distance'])
                                f.write(f"{uid},Distance={distance_ft:.2f}\n")
                                f.write(f"{uid},ATA={wez_ata:.2f}\n")
                            else:
                                distance_ft = meters_to_feet(params['distance'])
                                f.write(f"{uid},Distance={distance_ft:.2f}\n")
                                f.write(f"{uid},ATA={params['ata_deg']:.2f}\n")
                            f.write(f"{uid},AA={params['aa_deg']:.2f}\n")
                            f.write(f"{uid},HCA={params['hca_deg']:.2f}\n")
                            f.write(f"{uid},TAU={params['tau_deg']:.2f}\n")
                            f.write(f"{uid},ClosureRate={ms_to_knots(params['closure_rate']):.2f}\n")
                            f.write(f"{uid},Reward={agent_reward:.4f}\n")
                            current_health = health1.current_health if i == 0 else health2.current_health
                            f.write(f"{uid},Health={current_health:.1f}\n")
                            if wez_debug and 'in_wez1' in wez_debug:
                                in_wez = wez_debug['in_wez1'] if i == 0 else wez_debug['in_wez2']
                                f.write(f"{uid},InWEZ={'True' if in_wez else 'False'}\n")
                            task = task1 if i == 0 else task2
                            tree_name_i = tree1_name if i == 0 else tree2_name
                            color = "Blue" if i == 0 else "Red"
                            if hasattr(task, 'get_last_active_nodes'):
                                active_nodes = task.get_last_active_nodes()
                                if active_nodes:
                                    action_nodes = [n for n, s in active_nodes if s == 'SUCCESS']
                                    if action_nodes:
                                        active_action = action_nodes[-1]
                                        f.write(f"{uid},ActiveNode={active_action}\n")
                                        path = ">".join([n for n, s in active_nodes])
                                        f.write(f"{uid},NodePath={path}\n")
                                        prev_node_key = f"_prev_node_{uid}"
                                        prev_node = getattr(self, prev_node_key, None)
                                        f.write(f"{uid},Label=[{color}] {active_action}\n")
                                        if prev_node != active_action:
                                            setattr(self, prev_node_key, active_action)
                                            f.write(f"0,Event=Message|{uid}|[{color}] {tree_name_i}: {active_action}\n")
                                            f.write(f"0,Event=Debug|{uid}|Path: {path}\n")
                except Exception:
                    pass

            total_reward_1 += reward1
            total_reward_2 += reward2
            step_count += 1
            done = dones.any() if isinstance(dones, np.ndarray) else dones

            if verbose and step_count % 50 == 0:
                print(f"  Step {step_count}: reward={reward}")

        env.close()

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
        _print(f"  {tree1_name}: {health1.current_health:.1f} HP (데미지 {health2.total_damage_dealt:.1f} 가함)")
        _print(f"  {tree2_name}: {health2.current_health:.1f} HP (데미지 {health1.total_damage_dealt:.1f} 가함)")

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
