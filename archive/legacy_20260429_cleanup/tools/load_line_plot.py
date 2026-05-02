import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── 計算值（DigiKey 驗算過）──────────────────────────
ICQ   = 0.839   # mA
VCEQ  = 3.84    # V

# 直流負載線端點
VCE_dc_cut = 10.0   # V  (截止點)
IC_dc_sat  = 1.370  # mA (飽和點)

# 交流負載線端點
VCE_ac_cut = 5.14   # V
IC_ac_sat  = 3.32   # mA

# ── 繪圖設定 ─────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 7))
fig.patch.set_facecolor('#0d1117')
ax.set_facecolor('#161b22')

# 格線
ax.grid(True, color='#30363d', linewidth=0.8, linestyle='--', zorder=0)

# 四個象限：將軸延伸到負值
xlim = (-1.2, 11.5)
ylim = (-0.45, 3.8)
ax.set_xlim(xlim)
ax.set_ylim(ylim)

# 畫軸線（黑色十字）
ax.axhline(0, color='#8b949e', linewidth=1.2, zorder=1)
ax.axvline(0, color='#8b949e', linewidth=1.2, zorder=1)

# ── 直流負載線 ────────────────────────────────────────
dc_x = [0,          VCE_dc_cut]
dc_y = [IC_dc_sat,  0         ]
ax.plot(dc_x, dc_y,
        color='#58a6ff', linewidth=2.5, label='DC Load Line', zorder=3)

# ── 交流負載線 ────────────────────────────────────────
ac_x = [0,          VCE_ac_cut]
ac_y = [IC_ac_sat,  0         ]
ax.plot(ac_x, ac_y,
        color='#f78166', linewidth=2.5, linestyle='--',
        label='AC Load Line', zorder=3)

# ── Q 點 ─────────────────────────────────────────────
ax.plot(VCEQ, ICQ,
        'o', color='#ffa657', markersize=12, zorder=5,
        label=f'Q point  ({VCEQ} V,  {ICQ} mA)')

# Q 點虛線輔助線
ax.plot([VCEQ, VCEQ], [0, ICQ],
        color='#ffa657', linewidth=1.0, linestyle=':', zorder=2)
ax.plot([0, VCEQ],    [ICQ, ICQ],
        color='#ffa657', linewidth=1.0, linestyle=':', zorder=2)

# ── 標記端點 ─────────────────────────────────────────
kw = dict(fontsize=9, color='#c9d1d9', zorder=6)

# DC 端點
ax.annotate(f'({VCE_dc_cut} V, 0)',
            xy=(VCE_dc_cut, 0), xytext=(VCE_dc_cut-0.3, 0.12),
            fontsize=9, color='#58a6ff',
            arrowprops=dict(arrowstyle='->', color='#58a6ff', lw=1))
ax.annotate(f'(0, {IC_dc_sat} mA)',
            xy=(0, IC_dc_sat), xytext=(0.4, IC_dc_sat+0.08),
            fontsize=9, color='#58a6ff',
            arrowprops=dict(arrowstyle='->', color='#58a6ff', lw=1))

# AC 端點
ax.annotate(f'({VCE_ac_cut} V, 0)',
            xy=(VCE_ac_cut, 0), xytext=(VCE_ac_cut-1.0, -0.22),
            fontsize=9, color='#f78166',
            arrowprops=dict(arrowstyle='->', color='#f78166', lw=1))
ax.annotate(f'(0, {IC_ac_sat} mA)',
            xy=(0, IC_ac_sat), xytext=(0.4, IC_ac_sat+0.08),
            fontsize=9, color='#f78166',
            arrowprops=dict(arrowstyle='->', color='#f78166', lw=1))

# Q 點標籤
ax.annotate(f'  Q ({VCEQ} V, {ICQ} mA)',
            xy=(VCEQ, ICQ), xytext=(VCEQ+0.5, ICQ+0.18),
            fontsize=10, color='#ffa657', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='#ffa657', lw=1.2))

# ── 軸標籤 ───────────────────────────────────────────
ax.set_xlabel('$V_{CE}$ (V)', fontsize=13, color='#c9d1d9', labelpad=8)
ax.set_ylabel('$I_C$ (mA)',   fontsize=13, color='#c9d1d9', labelpad=8)
ax.tick_params(colors='#8b949e', labelsize=10)
for spine in ax.spines.values():
    spine.set_edgecolor('#30363d')

# ── 標題 ─────────────────────────────────────────────
ax.set_title('BJT 交直流負載線\nβ=120   V$_A$=80V   V⁺=+5V   V⁻=−5V   R$_C$=2.3kΩ   R$_E$=5kΩ   R$_L$=5kΩ',
             fontsize=12, color='#e6edf3', pad=14)

# ── 圖例 ─────────────────────────────────────────────
leg = ax.legend(fontsize=10, loc='upper right',
                facecolor='#21262d', edgecolor='#30363d',
                labelcolor='#c9d1d9', framealpha=0.9)

# ── 象限標籤（說明這是第一象限操作區） ─────────────
ax.text(-0.9, -0.35, 'III', fontsize=11, color='#484f58', style='italic')
ax.text( 9.5, -0.35, 'IV',  fontsize=11, color='#484f58', style='italic')
ax.text(-0.9,  3.55, 'II',  fontsize=11, color='#484f58', style='italic')
ax.text( 9.5,  3.55, 'I',   fontsize=11, color='#484f58', style='italic')

plt.tight_layout()
plt.savefig(r'd:\agent_test\load_line.png', dpi=150,
            bbox_inches='tight', facecolor=fig.get_facecolor())
print("圖片已儲存：d:\\agent_test\\load_line.png")
plt.show()
