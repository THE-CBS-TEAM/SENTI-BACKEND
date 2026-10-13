import io
import base64
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Sentimentri Brand Palette
COLORS = {
    'primary': '#059669',       # Emerald green
    'primary_light': '#10b981',
    'primary_dark': '#047857',
    'accent': '#7c3aed',        # Violet accent
    'accent_light': '#8b5cf6',
    'positive': '#10b981',
    'neutral': '#94a3b8',
    'negative': '#ef4444',
    'text_dark': '#1a202c',
    'text_mid': '#4a5568',
    'text_light': '#718096',
    'bg_light': '#f8fafc',
    'bg_card': '#f7fafc',
    'border': '#e2e8f0',
    # Platform colors
    'instagram': '#E1306C',
    'tiktok': '#00f2ea',
    'twitter': '#1DA1F2',
    # Emotion category colors
    'excited': '#f59e0b',
    'happy': '#10b981',
    'curious': '#3b82f6',
    'disappointed': '#f97316',
    'angry': '#ef4444',
    'inspired': '#8b5cf6',
    'neutral_emotion': '#94a3b8',
}

THEME_PALETTES = {
    'DARK': {
        'fig_bg': '#0c0c0e',
        'axes_bg': '#0c0c0e',
        'border': '#27272a',
        'grid': '#27272a',
        'text_title': '#ffffff',
        'text_body': '#f4f4f5',
        'text_muted': '#a1a1aa',
        'alt_row': '#141418',
        'legend_bg': '#141417',
        'legend_border': '#27272a',
        'legend_text': '#f4f4f5',
        'donut_edge': '#0c0c0e',
    },
    'LIGHT': {
        'fig_bg': '#f8fafc',
        'axes_bg': '#f8fafc',
        'border': '#e2e8f0',
        'grid': '#e2e8f0',
        'text_title': '#0f172a',
        'text_body': '#1e293b',
        'text_muted': '#64748b',
        'alt_row': '#f1f5f9',
        'legend_bg': '#ffffff',
        'legend_border': '#e2e8f0',
        'legend_text': '#1e293b',
        'donut_edge': '#f8fafc',
    }
}


def _get_theme_palette(theme='DARK'):
    norm = str(theme).upper() if theme else 'DARK'
    return THEME_PALETTES.get(norm, THEME_PALETTES['DARK'])


def _fig_to_base64(fig):
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor(), edgecolor='none')
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    return b64


def _setup_matplotlib(theme='DARK'):
    """Configure matplotlib for headless server-side rendering matching workspace theme."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    pal = _get_theme_palette(theme)
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans'],
        'font.size': 10,
        'axes.titlesize': 13,
        'axes.labelsize': 10,
        'xtick.labelsize': 9,
        'ytick.labelsize': 9,
        'legend.fontsize': 9,
        'figure.facecolor': pal['fig_bg'],
        'axes.facecolor': pal['axes_bg'],
        'axes.edgecolor': pal['border'],
        'axes.grid': True,
        'grid.alpha': 0.4,
        'grid.color': pal['grid'],
        'text.color': pal['text_body'],
        'axes.labelcolor': pal['text_muted'],
        'xtick.color': pal['text_muted'],
        'ytick.color': pal['text_muted'],
    })
    return plt, pal


class ChartGenerator:
    """Generates server-side charts as base64-encoded PNG images blending with workspace themes."""

    @classmethod
    def generate_engagement_velocity_chart(cls, daily_data, theme='DARK'):
        """
        Generate a daily engagement line chart across the campaign period.
        """
        plt, pal = _setup_matplotlib(theme)
        
        if not daily_data:
            return cls._generate_empty_chart(plt, "No engagement timeline data available", theme=theme)
        
        sorted_dates = sorted(daily_data.keys())
        
        fig, ax = plt.subplots(figsize=(10, 4))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        # Plot per-platform lines if data exists
        platforms = {'IG': ('Instagram', COLORS['instagram']), 
                     'TT': ('TikTok', COLORS['tiktok']),
                     'X': ('Twitter/X', COLORS['twitter'])}
        
        for platform_key, (label, color) in platforms.items():
            values = [daily_data[d].get(platform_key, 0) for d in sorted_dates]
            if any(v > 0 for v in values):
                ax.plot(range(len(sorted_dates)), values, color=color, 
                        linewidth=2, marker='o', markersize=4, label=label, alpha=0.9)
        
        # Always plot total engagement line
        total_values = [daily_data[d].get('total', 0) for d in sorted_dates]
        ax.plot(range(len(sorted_dates)), total_values, color=COLORS['primary_light'],
                linewidth=2.5, marker='s', markersize=5, label='Total', zorder=5)
        
        # Fill under total curve
        ax.fill_between(range(len(sorted_dates)), total_values, alpha=0.12, color=COLORS['primary_light'])
        
        # X-axis labels
        n = max(1, len(sorted_dates) // 10)
        tick_positions = list(range(0, len(sorted_dates), n))
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([sorted_dates[i] for i in tick_positions], rotation=45, ha='right', color=pal['text_muted'])
        
        ax.tick_params(axis='both', colors=pal['text_muted'])
        ax.set_title('Daily Engagement Volume', fontweight='bold', color=pal['text_title'], pad=12)
        ax.set_ylabel('Engagement Actions', color=pal['text_muted'])
        
        legend = ax.legend(loc='upper left', framealpha=0.9, facecolor=pal['legend_bg'], edgecolor=pal['legend_border'])
        for text in legend.get_texts():
            text.set_color(pal['legend_text'])
            
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(pal['border'])
        ax.spines['bottom'].set_color(pal['border'])
        
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_sentiment_donut_chart(cls, positive, neutral, negative, theme='DARK'):
        """
        Generate a donut chart showing sentiment distribution.
        """
        plt, pal = _setup_matplotlib(theme)
        
        total = positive + neutral + negative
        if total == 0:
            return cls._generate_empty_chart(plt, "No sentiment data available", theme=theme)
        
        fig, ax = plt.subplots(figsize=(5, 5))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        values = [positive, neutral, negative]
        colors = [COLORS['positive'], COLORS['neutral'], COLORS['negative']]
        labels = [
            f"Positive\n{positive:,} ({round(positive/total*100, 1)}%)",
            f"Neutral\n{neutral:,} ({round(neutral/total*100, 1)}%)",
            f"Negative\n{negative:,} ({round(negative/total*100, 1)}%)"
        ]
        
        wedges, texts = ax.pie(
            values, colors=colors, startangle=90,
            wedgeprops={'width': 0.4, 'edgecolor': pal['donut_edge'], 'linewidth': 2}
        )
        
        # Center text
        ax.text(0, 0.05, f'{total:,}', ha='center', va='center',
                fontsize=20, fontweight='bold', color=pal['text_title'])
        ax.text(0, -0.12, 'TOTAL', ha='center', va='center',
                fontsize=8, color=pal['text_muted'], fontweight='bold')
        
        # Legend
        legend = ax.legend(wedges, labels, loc='center left', bbox_to_anchor=(1, 0.5),
                           frameon=False, fontsize=10)
        for text in legend.get_texts():
            text.set_color(pal['text_body'])
        
        ax.set_title('Comment Sentiment Distribution', fontweight='bold',
                      color=pal['text_title'], pad=15, fontsize=13)
        
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_emotion_category_chart(cls, emotion_counts, theme='DARK'):
        """
        Generate a horizontal bar chart for emotion category distribution.
        """
        plt, pal = _setup_matplotlib(theme)
        
        if not emotion_counts or all(v == 0 for v in emotion_counts.values()):
            return cls._generate_empty_chart(plt, "No emotion category data available", theme=theme)
        
        emotion_config = OrderedDict([
            ('EXCITED', ('Excited', COLORS['excited'])),
            ('HAPPY', ('Happy', COLORS['happy'])),
            ('CURIOUS', ('Curious', COLORS['curious'])),
            ('INSPIRED', ('Inspired', COLORS['inspired'])),
            ('NEUTRAL', ('Neutral', COLORS['neutral_emotion'])),
            ('DISAPPOINTED', ('Disappointed', COLORS['disappointed'])),
            ('ANGRY', ('Angry', COLORS['angry'])),
        ])
        
        labels = []
        values = []
        colors = []
        for key, (label, color) in emotion_config.items():
            count = emotion_counts.get(key, 0)
            if count > 0:
                labels.append(label)
                values.append(count)
                colors.append(color)
        
        if not values:
            return cls._generate_empty_chart(plt, "No emotion category data available", theme=theme)
        
        fig, ax = plt.subplots(figsize=(8, max(3, len(labels) * 0.6)))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        y_pos = range(len(labels))
        bars = ax.barh(y_pos, values, color=colors, height=0.6, edgecolor=pal['donut_edge'], linewidth=0.5)
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontweight='medium', color=pal['text_body'])
        ax.tick_params(axis='both', colors=pal['text_muted'])
        ax.invert_yaxis()
        ax.set_xlabel('Comment Count', color=pal['text_muted'])
        ax.set_title('Audience Emotion Breakdown', fontweight='bold',
                      color=pal['text_title'], pad=12)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(pal['border'])
        ax.spines['bottom'].set_color(pal['border'])
        
        # Value labels on bars
        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + max(values) * 0.02, bar.get_y() + bar.get_height() / 2,
                    f'{val:,}', va='center', fontsize=9, color=pal['text_muted'], fontweight='bold')
        
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_platform_comparison_chart(cls, platform_data, theme='DARK'):
        """
        Generate a grouped bar chart comparing metrics across platforms.
        """
        plt, pal = _setup_matplotlib(theme)
        
        if not platform_data:
            return cls._generate_empty_chart(plt, "No platform data available", theme=theme)
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
        fig.set_facecolor(pal['fig_bg'])
        ax1.set_facecolor(pal['axes_bg'])
        ax2.set_facecolor(pal['axes_bg'])
        
        platform_colors = {
            'IG': COLORS['instagram'],
            'TT': COLORS['tiktok'],
            'X': COLORS['twitter']
        }
        platform_labels = {'IG': 'Instagram', 'TT': 'TikTok', 'X': 'Twitter/X'}
        
        names = [platform_labels.get(p['platform'], p['platform']) for p in platform_data]
        colors = [platform_colors.get(p['platform'], COLORS['primary']) for p in platform_data]
        
        # Views chart
        views = [p['views'] for p in platform_data]
        bars1 = ax1.bar(names, views, color=colors, edgecolor=pal['donut_edge'], linewidth=1, width=0.5)
        ax1.set_title('Views by Platform', fontweight='bold', color=pal['text_title'], pad=10)
        ax1.tick_params(axis='both', colors=pal['text_muted'])
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['left'].set_color(pal['border'])
        ax1.spines['bottom'].set_color(pal['border'])
        for bar, val in zip(bars1, views):
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:,}', ha='center', va='bottom', fontsize=9, fontweight='bold',
                     color=pal['text_muted'])
        
        # Engagement chart
        engagement = [p['engagement'] for p in platform_data]
        bars2 = ax2.bar(names, engagement, color=colors, edgecolor=pal['donut_edge'], linewidth=1, width=0.5)
        ax2.set_title('Engagement by Platform', fontweight='bold', color=pal['text_title'], pad=10)
        ax2.tick_params(axis='both', colors=pal['text_muted'])
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.spines['left'].set_color(pal['border'])
        ax2.spines['bottom'].set_color(pal['border'])
        for bar, val in zip(bars2, engagement):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:,}', ha='center', va='bottom', fontsize=9, fontweight='bold',
                     color=pal['text_muted'])
        
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_creator_comparison_chart(cls, creators_data, theme='DARK'):
        """
        Generate a horizontal bar chart ranking creators by total engagement.
        """
        plt, pal = _setup_matplotlib(theme)
        
        if not creators_data:
            return cls._generate_empty_chart(plt, "No creator data available", theme=theme)
        
        # Sort by engagement descending
        sorted_creators = sorted(creators_data, key=lambda x: x['engagement'], reverse=True)[:15]
        
        fig, ax = plt.subplots(figsize=(9, max(3, len(sorted_creators) * 0.55)))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        names = [c['name'] for c in sorted_creators]
        engagements = [c['engagement'] for c in sorted_creators]
        centi_scores = [c.get('centi_score', 0) for c in sorted_creators]
        
        y_pos = range(len(names))
        
        # Add alternating row backgrounds
        for i in y_pos:
            if i % 2 == 0:
                ax.axhspan(i - 0.5, i + 0.5, color=pal['alt_row'], zorder=0, alpha=0.6)
                
        # Use brand accent color for all bars
        bar_color = COLORS.get('accent_light', '#8b5cf6')
        
        bars = ax.barh(y_pos, engagements, color=bar_color, height=0.45, 
                       edgecolor=pal['donut_edge'], linewidth=0, zorder=3)
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontweight='medium', color=pal['text_body'], fontsize=10)
        ax.invert_yaxis()
        
        # Remove all borders for cleaner look
        for spine in ax.spines.values():
            spine.set_visible(False)
            
        ax.set_xlabel('Total Engagement', color=pal['text_muted'], fontsize=10)
        ax.set_title('Creator Performance Ranking', fontweight='bold',
                      color=pal['text_title'], pad=15, fontsize=14)
        
        ax.tick_params(axis='both', which='both', length=0, colors=pal['text_muted'])
        
        # Value labels + centi score badges
        max_eng = max(engagements) if engagements else 1
        ax.set_xlim(0, max_eng * 1.35)
        for bar, val, score in zip(bars, engagements, centi_scores):
            label_text = f'{val:,}  (Centi: {score}/100)'
            ax.text(bar.get_width() + max_eng * 0.02, bar.get_y() + bar.get_height() / 2,
                    label_text, va='center', fontsize=9, color=pal['text_muted'], fontweight='medium')
        
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_benchmark_comparison_chart(cls, creators_benchmark_data, theme='DARK'):
        """
        Generate a grouped bar chart comparing sponsored vs organic performance.
        """
        plt, pal = _setup_matplotlib(theme)
        import numpy as np
        
        if not creators_benchmark_data:
            return cls._generate_empty_chart(plt, "No benchmark comparison data available", theme=theme)
        
        data = creators_benchmark_data[:8]
        
        fig, ax = plt.subplots(figsize=(10, 4.5))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        names = [d['name'] for d in data]
        sponsored = [d['sponsored_eng'] for d in data]
        organic = [d['organic_avg_eng'] for d in data]
        
        x = np.arange(len(names))
        width = 0.35
        
        bars1 = ax.bar(x - width / 2, sponsored, width, label='Campaign (Sponsored)',
                       color=COLORS['accent_light'], edgecolor=pal['donut_edge'], linewidth=1)
        bars2 = ax.bar(x + width / 2, organic, width, label='Organic Baseline',
                       color=COLORS['neutral'], edgecolor=pal['donut_edge'], linewidth=1)
        
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=30, ha='right', color=pal['text_body'])
        ax.tick_params(axis='both', colors=pal['text_muted'])
        ax.set_ylabel('Total Engagement', color=pal['text_muted'])
        ax.set_title('Sponsored vs Organic Engagement Benchmark', fontweight='bold',
                      color=pal['text_title'], pad=12)
        
        legend = ax.legend(framealpha=0.9, facecolor=pal['legend_bg'], edgecolor=pal['legend_border'])
        for text in legend.get_texts():
            text.set_color(pal['legend_text'])
            
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(pal['border'])
        ax.spines['bottom'].set_color(pal['border'])
        
        # Diff labels
        for i, d in enumerate(data):
            diff = d.get('diff_pct', 0)
            color = COLORS['positive'] if diff >= 0 else COLORS['negative']
            sign = '+' if diff >= 0 else ''
            y_pos = max(sponsored[i], organic[i])
            ax.text(i, y_pos * 1.03, f'{sign}{diff}%', ha='center', fontsize=8,
                    fontweight='bold', color=color)
        
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_budget_breakdown_chart(cls, influencer_fees, theme='DARK'):
        """
        Generate a pie chart showing budget allocation across influencers.
        """
        plt, pal = _setup_matplotlib(theme)
        
        if not influencer_fees or all(f['fee'] == 0 for f in influencer_fees):
            return cls._generate_empty_chart(plt, "No budget allocation data available", theme=theme)
        
        data = [f for f in influencer_fees if f['fee'] > 0]
        if not data:
            return cls._generate_empty_chart(plt, "No budget allocation data available", theme=theme)
        
        fig, ax = plt.subplots(figsize=(6, 5))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        names = [d['name'] for d in data]
        fees = [float(d['fee']) for d in data]
        total_fee = sum(fees)
        
        try:
            import matplotlib
            if hasattr(matplotlib, 'colormaps'):
                cmap = matplotlib.colormaps.get_cmap('Set3')
            else:
                cmap = plt.get_cmap('Set3')
        except Exception:
            cmap = plt.get_cmap('tab10')
        colors = [cmap(i % 10) for i in range(len(data))]
        
        labels = [f"{n}\n${f:,.0f} ({f/total_fee*100:.1f}%)" for n, f in zip(names, fees)]
        
        wedges, texts = ax.pie(
            fees, colors=colors, startangle=140,
            wedgeprops={'edgecolor': pal['donut_edge'], 'linewidth': 2}
        )
        
        legend = ax.legend(wedges, labels, loc='center left', bbox_to_anchor=(1, 0.5),
                           frameon=False, fontsize=9)
        for text in legend.get_texts():
            text.set_color(pal['text_body'])
            
        ax.set_title('Influencer Fee Allocation', fontweight='bold',
                      color=pal['text_title'], pad=15, fontsize=13)
        
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_sentiment_ratio_bars_chart(cls, creators_sentiment_data, theme='DARK'):
        """
        Generate a stacked horizontal bar chart showing positive, neutral, negative sentiment ratio per creator.
        """
        plt, pal = _setup_matplotlib(theme)
        
        if not creators_sentiment_data:
            return cls._generate_empty_chart(plt, "No sentiment ratio data available", theme=theme)
            
        fig, ax = plt.subplots(figsize=(9, max(3.3, len(creators_sentiment_data) * 0.65)))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        names = [c['name'] for c in creators_sentiment_data]
        positives = [c.get('positive', 0) for c in creators_sentiment_data]
        neutrals = [c.get('neutral', 0) for c in creators_sentiment_data]
        negatives = [c.get('negative', 0) for c in creators_sentiment_data]
        
        y_pos = range(len(names))
        
        bars_pos = ax.barh(y_pos, positives, label='Positive', color=COLORS['positive'], height=0.55)
        bars_neu = ax.barh(y_pos, neutrals, left=positives, label='Neutral', color=COLORS['neutral'], height=0.55)
        left_neg = [p + n for p, n in zip(positives, neutrals)]
        bars_neg = ax.barh(y_pos, negatives, left=left_neg, label='Negative', color=COLORS['negative'], height=0.55)
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontweight='medium', color=pal['text_body'])
        ax.tick_params(axis='both', colors=pal['text_muted'])
        ax.invert_yaxis()
        ax.set_xlabel('Sentiment Percentage (%)', color=pal['text_muted'])
        ax.set_xlim(0, 100)
        ax.set_title('Creator Audience Sentiment Ratio', fontweight='bold', color=pal['text_title'], pad=12)
        
        legend = ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.25), ncol=3, framealpha=0.9,
                           facecolor=pal['legend_bg'], edgecolor=pal['legend_border'])
        for text in legend.get_texts():
            text.set_color(pal['legend_text'])
            
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(pal['border'])
        ax.spines['bottom'].set_color(pal['border'])
        
        for i, (pos, neu, neg) in enumerate(zip(positives, neutrals, negatives)):
            if pos > 8:
                ax.text(pos / 2, i, f'{int(pos)}%', va='center', ha='center', color='white', fontsize=8, fontweight='bold')
            if neu > 8:
                ax.text(pos + neu / 2, i, f'{int(neu)}%', va='center', ha='center', color='white', fontsize=8, fontweight='bold')
            if neg > 8:
                ax.text(pos + neu + neg / 2, i, f'{int(neg)}%', va='center', ha='center', color='white', fontsize=8, fontweight='bold')
                 
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def generate_native_vs_campaign_chart(cls, influencers_data, theme='DARK'):
        """
        Creates a grouped bar chart comparing each creator's native post averages vs their campaign post metrics.
        """
        plt, pal = _setup_matplotlib(theme)
        import numpy as np
        
        if not influencers_data:
            return cls._generate_empty_chart(plt, "No native vs campaign data available", theme=theme)
            
        data = influencers_data[:8]
        
        fig, ax = plt.subplots(figsize=(10, 4.5))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        
        names = [d.get('name', 'Unknown') for d in data]
        campaign = []
        organic = []
        diffs = []
        
        for d in data:
            if 'benchmark' in d and isinstance(d['benchmark'], dict):
                bm = d['benchmark']
                organic.append(bm.get('organic_avg_eng', 0))
                campaign.append(bm.get('sponsored_avg_eng', 0))
                diffs.append(bm.get('diff_pct', 0))
            else:
                organic.append(d.get('benchmark.organic_avg_eng', 0))
                campaign.append(d.get('benchmark.sponsored_avg_eng', 0))
                diffs.append(d.get('benchmark.diff_pct', 0))
            
        x = np.arange(len(names))
        width = 0.35
        
        bars_organic = ax.bar(x - width / 2, organic, width, label='Organic Baseline',
                              color=COLORS['neutral'], edgecolor=pal['donut_edge'], linewidth=1)
        bars_campaign = ax.bar(x + width / 2, campaign, width, label='Campaign Content',
                               color=COLORS['primary_light'], edgecolor=pal['donut_edge'], linewidth=1)
                               
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=30, ha='right', color=pal['text_body'])
        ax.tick_params(axis='both', colors=pal['text_muted'])
        ax.set_ylabel('Avg Engagement', color=pal['text_muted'])
        ax.set_title('Native vs Campaign Content Performance', fontweight='bold',
                      color=pal['text_title'], pad=12)
        
        legend = ax.legend(framealpha=0.9, facecolor=pal['legend_bg'], edgecolor=pal['legend_border'])
        for text in legend.get_texts():
            text.set_color(pal['legend_text'])
            
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(pal['border'])
        ax.spines['bottom'].set_color(pal['border'])
        
        for i, diff in enumerate(diffs):
            color = COLORS['positive'] if diff >= 0 else COLORS['negative']
            sign = '+' if diff > 0 else ''
            y_pos = max(campaign[i], organic[i])
            ax.text(i, y_pos * 1.05, f'{sign}{diff}%', ha='center', fontsize=8,
                    fontweight='bold', color=color)
                    
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64

    @classmethod
    def _generate_empty_chart(cls, plt, message, theme='DARK'):
        """Generate a placeholder chart with a message when no data is available."""
        pal = _get_theme_palette(theme)
        fig, ax = plt.subplots(figsize=(8, 3))
        fig.set_facecolor(pal['fig_bg'])
        ax.set_facecolor(pal['axes_bg'])
        ax.text(0.5, 0.5, message, ha='center', va='center',
                fontsize=12, color=pal['text_muted'], style='italic')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        plt.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
