"""
ACMI 리플레이 파일 3D 시각화 스크립트
"""

import sys
from pathlib import Path
import re
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def parse_acmi_file(filepath):
    """ACMI 파일 파싱
    
    Returns:
        dict: {
            'A0100': {'positions': [], 'times': [], 'aa': [], 'ata': [], 'hca': [], 'distance': []},
            'B0100': {'positions': [], 'times': [], 'aa': [], 'ata': [], 'hca': [], 'distance': []}
        }
    """
    data = {
        'A0100': {
            'positions': [],
            'times': [],
            'aa': [],
            'ata': [],
            'hca': [],
            'distance': [],
            'heading': [],
            'name': ''
        },
        'B0100': {
            'positions': [],
            'times': [],
            'aa': [],
            'ata': [],
            'hca': [],
            'distance': [],
            'heading': [],
            'name': ''
        }
    }
    
    current_time = 0.0
    current_data = {'A0100': {}, 'B0100': {}}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # 시간 마커
            if line.startswith('#'):
                # 현재 데이터 저장
                for agent_id in ['A0100', 'B0100']:
                    if 'T' in current_data[agent_id]:
                        pos = current_data[agent_id]['T']
                        data[agent_id]['positions'].append(pos)
                        data[agent_id]['times'].append(current_time)
                        data[agent_id]['aa'].append(current_data[agent_id].get('AA', 0))
                        data[agent_id]['ata'].append(current_data[agent_id].get('ATA', 0))
                        data[agent_id]['hca'].append(current_data[agent_id].get('HCA', 0))
                        data[agent_id]['distance'].append(current_data[agent_id].get('Distance', 0))
                        data[agent_id]['heading'].append(current_data[agent_id].get('HDG', 0))
                
                # 새 시간
                current_time = float(line[1:])
                current_data = {'A0100': {}, 'B0100': {}}
                continue
            
            # 데이터 라인
            if ',' in line:
                parts = line.split(',', 1)
                agent_id = parts[0]
                
                if agent_id not in ['A0100', 'B0100']:
                    continue
                
                # 속성 파싱
                for attr in parts[1].split(','):
                    if '=' in attr:
                        key, value = attr.split('=', 1)
                        
                        if key == 'T':
                            # 위치: Lon|Lat|Alt|U|V|Heading
                            coords = value.split('|')
                            lon = float(coords[0])
                            lat = float(coords[1])
                            alt = float(coords[2])
                            current_data[agent_id]['T'] = [lon, lat, alt]
                        elif key == 'CallSign':
                            data[agent_id]['name'] = value
                        elif key == 'AA':
                            current_data[agent_id]['AA'] = float(value)
                        elif key == 'ATA':
                            current_data[agent_id]['ATA'] = float(value)
                        elif key == 'HCA':
                            current_data[agent_id]['HCA'] = float(value)
                        elif key == 'Distance':
                            current_data[agent_id]['Distance'] = float(value)
                        elif key == 'HDG':
                            current_data[agent_id]['HDG'] = float(value)
    
    return data


def plot_3d_trajectory(data, output_path=None):
    """3D 궤적 플롯"""
    fig = plt.figure(figsize=(16, 12))
    
    # 3D 궤적
    ax1 = fig.add_subplot(2, 2, 1, projection='3d')
    
    # Agent A (aggressive_fighter)
    pos_a = np.array(data['A0100']['positions'])
    if len(pos_a) > 0:
        # 경도를 미터로 변환 (대략적)
        lon_a = (pos_a[:, 0] - 120) * 111320 * np.cos(np.radians(60))
        lat_a = (pos_a[:, 1] - 60) * 111320
        alt_a = pos_a[:, 2]
        
        ax1.plot(lon_a, lat_a, alt_a, 'b-', linewidth=2, label=data['A0100']['name'], alpha=0.7)
        ax1.scatter(lon_a[0], lat_a[0], alt_a[0], c='blue', marker='o', s=100, label='Start A')
        ax1.scatter(lon_a[-1], lat_a[-1], alt_a[-1], c='blue', marker='x', s=100, label='End A')
    
    # Agent B (defensive_evader)
    pos_b = np.array(data['B0100']['positions'])
    if len(pos_b) > 0:
        lon_b = (pos_b[:, 0] - 120) * 111320 * np.cos(np.radians(60))
        lat_b = (pos_b[:, 1] - 60) * 111320
        alt_b = pos_b[:, 2]
        
        ax1.plot(lon_b, lat_b, alt_b, 'r-', linewidth=2, label=data['B0100']['name'], alpha=0.7)
        ax1.scatter(lon_b[0], lat_b[0], alt_b[0], c='red', marker='o', s=100, label='Start B')
        ax1.scatter(lon_b[-1], lat_b[-1], alt_b[-1], c='red', marker='x', s=100, label='End B')
    
    ax1.set_xlabel('East (m)', fontsize=10)
    ax1.set_ylabel('North (m)', fontsize=10)
    ax1.set_zlabel('Altitude (m)', fontsize=10)
    ax1.set_title('3D Trajectory', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    
    # 2D Top View
    ax2 = fig.add_subplot(2, 2, 2)
    if len(pos_a) > 0:
        ax2.plot(lon_a, lat_a, 'b-', linewidth=2, label=data['A0100']['name'], alpha=0.7)
        ax2.scatter(lon_a[0], lat_a[0], c='blue', marker='o', s=100)
        ax2.scatter(lon_a[-1], lat_a[-1], c='blue', marker='x', s=100)
    if len(pos_b) > 0:
        ax2.plot(lon_b, lat_b, 'r-', linewidth=2, label=data['B0100']['name'], alpha=0.7)
        ax2.scatter(lon_b[0], lat_b[0], c='red', marker='o', s=100)
        ax2.scatter(lon_b[-1], lat_b[-1], c='red', marker='x', s=100)
    
    ax2.set_xlabel('East (m)', fontsize=10)
    ax2.set_ylabel('North (m)', fontsize=10)
    ax2.set_title('Top View (2D)', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.axis('equal')
    
    # AA, ATA, HCA 시간에 따른 변화
    ax3 = fig.add_subplot(2, 2, 3)
    times_a = data['A0100']['times']
    times_b = data['B0100']['times']
    
    if len(times_a) > 0:
        ax3.plot(times_a, data['A0100']['aa'], 'b-', linewidth=2, label=f"{data['A0100']['name']} AA", alpha=0.7)
        ax3.plot(times_a, data['A0100']['ata'], 'b--', linewidth=1.5, label=f"{data['A0100']['name']} ATA", alpha=0.5)
    if len(times_b) > 0:
        ax3.plot(times_b, data['B0100']['aa'], 'r-', linewidth=2, label=f"{data['B0100']['name']} AA", alpha=0.7)
        ax3.plot(times_b, data['B0100']['ata'], 'r--', linewidth=1.5, label=f"{data['B0100']['name']} ATA", alpha=0.5)
    
    ax3.axhline(y=60, color='g', linestyle=':', alpha=0.5, label='AA 60° (OBFM threshold)')
    ax3.axhline(y=120, color='orange', linestyle=':', alpha=0.5, label='AA 120° (DBFM threshold)')
    
    ax3.set_xlabel('Time (s)', fontsize=10)
    ax3.set_ylabel('Angle (degrees)', fontsize=10)
    ax3.set_title('AA & ATA over Time', fontsize=12, fontweight='bold')
    ax3.legend(fontsize=7, loc='best')
    ax3.grid(True, alpha=0.3)
    
    # Distance & HCA
    ax4 = fig.add_subplot(2, 2, 4)
    if len(times_a) > 0:
        ax4_twin = ax4.twinx()
        ax4.plot(times_a, data['A0100']['distance'], 'g-', linewidth=2, label='Distance', alpha=0.7)
        ax4_twin.plot(times_a, data['A0100']['hca'], 'purple', linewidth=2, label='HCA', alpha=0.7)
        
        ax4.axhline(y=1500, color='orange', linestyle=':', alpha=0.5, label='1.5km')
        ax4.axhline(y=3000, color='red', linestyle=':', alpha=0.5, label='3km')
        ax4_twin.axhline(y=150, color='purple', linestyle=':', alpha=0.3, label='HCA 150° (head-on)')
        
        ax4.set_xlabel('Time (s)', fontsize=10)
        ax4.set_ylabel('Distance (m)', fontsize=10, color='g')
        ax4_twin.set_ylabel('HCA (degrees)', fontsize=10, color='purple')
        ax4.set_title('Distance & HCA over Time', fontsize=12, fontweight='bold')
        
        lines1, labels1 = ax4.get_legend_handles_labels()
        lines2, labels2 = ax4_twin.get_legend_handles_labels()
        ax4.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc='best')
        ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {output_path}")
    
    return fig


def analyze_engagement(data):
    """교전 패턴 분석"""
    print("\n" + "=" * 60)
    print("  교전 패턴 분석")
    print("=" * 60)
    
    for agent_id, agent_name in [('A0100', data['A0100']['name']), ('B0100', data['B0100']['name'])]:
        print(f"\n{agent_name}:")
        
        aa_values = data[agent_id]['aa']
        ata_values = data[agent_id]['ata']
        hca_values = data[agent_id]['hca']
        distance_values = data[agent_id]['distance']
        
        if len(aa_values) == 0:
            continue
        
        # AA 분석
        aa_arr = np.array(aa_values)
        obfm_time = np.sum(aa_arr < 60) * 0.2  # 0.2초 간격
        dbfm_time = np.sum(aa_arr > 120) * 0.2
        neutral_time = np.sum((aa_arr >= 60) & (aa_arr <= 120)) * 0.2
        
        print(f"  AA 분석:")
        print(f"    - OBFM 시간 (AA < 60°): {obfm_time:.1f}초 ({obfm_time/len(aa_values)*100:.1f}%)")
        print(f"    - DBFM 시간 (AA > 120°): {dbfm_time:.1f}초 ({dbfm_time/len(aa_values)*100:.1f}%)")
        print(f"    - Neutral 시간: {neutral_time:.1f}초 ({neutral_time/len(aa_values)*100:.1f}%)")
        print(f"    - 평균 AA: {np.mean(aa_arr):.1f}°")
        print(f"    - 최소/최대 AA: {np.min(aa_arr):.1f}° / {np.max(aa_arr):.1f}°")
        
        # 거리 분석
        dist_arr = np.array(distance_values)
        close_time = np.sum(dist_arr < 1500) * 0.2
        medium_time = np.sum((dist_arr >= 1500) & (dist_arr < 3000)) * 0.2
        far_time = np.sum(dist_arr >= 3000) * 0.2
        
        print(f"  거리 분석:")
        print(f"    - 근거리 (< 1.5km): {close_time:.1f}초 ({close_time/len(dist_arr)*100:.1f}%)")
        print(f"    - 중거리 (1.5~3km): {medium_time:.1f}초 ({medium_time/len(dist_arr)*100:.1f}%)")
        print(f"    - 원거리 (> 3km): {far_time:.1f}초 ({far_time/len(dist_arr)*100:.1f}%)")
        print(f"    - 평균 거리: {np.mean(dist_arr):.0f}m")
        print(f"    - 최소 거리: {np.min(dist_arr):.0f}m")
        
        # HCA 분석
        hca_arr = np.array(hca_values)
        head_on_time = np.sum(hca_arr > 150) * 0.2
        
        print(f"  HCA 분석:")
        print(f"    - 정면 대치 (> 150°): {head_on_time:.1f}초 ({head_on_time/len(hca_arr)*100:.1f}%)")
        print(f"    - 평균 HCA: {np.mean(hca_arr):.1f}°")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='ACMI 리플레이 파일 시각화')
    parser.add_argument('acmi_file', type=str, help='ACMI 파일 경로')
    parser.add_argument('--output', '-o', type=str, help='출력 이미지 경로', default=None)
    parser.add_argument('--show', action='store_true', help='플롯 표시')
    
    args = parser.parse_args()
    
    print(f"ACMI 파일 파싱 중: {args.acmi_file}")
    data = parse_acmi_file(args.acmi_file)
    
    print(f"\n파싱 완료:")
    print(f"  {data['A0100']['name']}: {len(data['A0100']['positions'])} 프레임")
    print(f"  {data['B0100']['name']}: {len(data['B0100']['positions'])} 프레임")
    
    # 분석
    analyze_engagement(data)
    
    # 플롯
    output_path = args.output
    if output_path is None:
        acmi_path = Path(args.acmi_file)
        output_path = acmi_path.parent / f"{acmi_path.stem}_analysis.png"
    
    print(f"\n3D 플롯 생성 중...")
    fig = plot_3d_trajectory(data, output_path)
    
    if args.show:
        plt.show()
    
    print("\n완료!")


if __name__ == "__main__":
    main()
