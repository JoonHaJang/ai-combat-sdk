"""Adaptive Eagle 전체 BFM 커스텀 노드 — 29개 (액션 22 + 조건 12 + EIM 1)"""

# 추적/공격 (OBFM)
from .custom_actions import SmartLeadPursuit, SmartPurePursuit, SmartLagPursuit
from .custom_actions import SmartGunAttack, SnapshotAttack

# 에너지 기동
from .custom_actions import SmartHighYoYo, SmartLowYoYo
from .custom_actions import SmartClimbingTurn, SmartDescendingTurn, VerticalFight

# 방어 (DBFM)
from .custom_actions import SmartBreakTurn, SmartDefensiveSpiral, ExtensionBreak
from .custom_actions import Jink, GunsDefense, LastDitch

# 교전/선회전 (HABFM)
from .custom_actions import SmartOneCircle, SmartTwoCircle
from .custom_actions import FlatScissors, RollingScissors

# 공전 탈출 + 유틸
from .custom_actions import HeadOnBreak, UnloadedExtension, Chandelle

# 데이터 기반 전술 조회 (counter_table_proposal_v3 런타임 dispatch)
from .custom_actions import TacticalLookup

# 조건 노드
from .custom_conditions import IsDefensiveGeometry, IsOffensiveGeometry, IsNeutralGeometry
from .custom_conditions import IsHighEnergy, IsLowEnergy
from .custom_conditions import IsCloseCombat, IsWEZOpportunity, IsUnderFire
from .custom_conditions import IsOneCircleSituation, IsTwoCircleSituation
from .custom_conditions import CustomOrbitDetector, IsOvershooting

# Rigid-behavior 감지 조건 (v5.1 피드백 분석 기반)
from .custom_conditions import IsLostPursuit, IsChaseStale, IsExtensionFailing

# EIM
from .custom_conditions import EnemyIntentIs
