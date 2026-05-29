import numpy as np
from .env_base import BaseEnv


class SingleCombatEnv(BaseEnv):
    """
    SingleCombatEnv is an one-to-one competitive environment.
    """
    def __init__(self, config_name: str):
        super().__init__(config_name)
        # Env-Specific initialization here!
        assert len(self.agents.keys()) == 2, f"{self.__class__.__name__} only supports 1v1 scenarios!"
        self.init_states = None

    def load_task(self):
        taskname = getattr(self.config, 'task', None)
        if taskname == 'singlecombat':
            from ..tasks.singlecombat_task import SingleCombatTask
            self.task = SingleCombatTask(self.config)
        elif taskname == 'hierarchical_singlecombat':
            from ..tasks.singlecombat_task import HierarchicalSingleCombatTask
            self.task = HierarchicalSingleCombatTask(self.config)
        elif taskname == 'singlecombat_dodge_missile':
            from ..tasks.singlecombat_with_missle_task import SingleCombatDodgeMissileTask
            self.task = SingleCombatDodgeMissileTask(self.config)
        elif taskname == 'singlecombat_shoot':
            from ..tasks.singlecombat_with_missle_task import SingleCombatShootMissileTask
            self.task = SingleCombatShootMissileTask(self.config)
        elif taskname == 'hierarchical_singlecombat_dodge_missile':
            from ..tasks.singlecombat_with_missle_task import HierarchicalSingleCombatDodgeMissileTask
            self.task = HierarchicalSingleCombatDodgeMissileTask(self.config)
        elif taskname == 'hierarchical_singlecombat_shoot':
            from ..tasks.singlecombat_with_missle_task import HierarchicalSingleCombatShootTask
            self.task = HierarchicalSingleCombatShootTask(self.config)
        elif taskname == 'HumanSingleCombat':
            from ..human_task.HumanSingleCombatTask import HumanSingleCombatTask
            self.task = HumanSingleCombatTask(self.config)
        else:
            raise NotImplementedError(f"Unknown taskname: {taskname}")

    def reset(self) -> np.ndarray:
        self.current_step = 0
        self.reset_simulators()
        self.task.reset(self)
        obs = self.get_obs()
        return self._pack(obs)

    def reset_simulators(self):
        # switch side
        if self.init_states is None:
            self.init_states = [sim.init_state.copy() for sim in self.agents.values()]
        # self.init_states[0].update({
        #     'ic_psi_true_deg': (self.np_random.uniform(270, 540))%360,
        #     'ic_h_sl_ft': self.np_random.uniform(17000, 23000),
        # })
        init_states = self.init_states.copy()
        # R15 (2026-05-29): scenario config 의 disable_side_switch 가 True 이면 shuffle 생략.
        # 우리/적 spawn 위치를 deterministic 으로 고정하여 us_attack / us_defend 같은
        # 분리된 fuzz 시나리오 가능.
        if not getattr(self.config, 'disable_side_switch', False):
            self.np_random.shuffle(init_states)
        for idx, sim in enumerate(self.agents.values()):
            sim.reload(init_states[idx])
        self._tempsims.clear()
