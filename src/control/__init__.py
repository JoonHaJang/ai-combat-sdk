"""
Control 모듈 - 공중전 제어 시스템

주요 컴포넌트:
- CombatGeometry: 공중전 기하학 계산 (ATA, AA, HCA, TAU 등)
- BFMClassifier: BFM 상황 분류 (OBFM, DBFM, HABFM)
- WeaponEngagementZone: Gun WEZ 판정 및 데미지 계산
- HealthGauge: 체력 관리 시스템
"""

from .combat_geometry import CombatGeometry, reduce_reflex_angle_deg
from .bfm_classifier import BFMClassifier, BFMSituation
from .health_manager import WeaponEngagementZone, HealthGauge

__all__ = [
    # Combat Geometry
    'CombatGeometry',
    'reduce_reflex_angle_deg',
    
    # BFM Classification
    'BFMClassifier',
    'BFMSituation',
    
    # Health & Damage
    'WeaponEngagementZone',
    'HealthGauge',
]
