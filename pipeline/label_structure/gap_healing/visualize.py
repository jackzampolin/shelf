import csv
import json
from pathlib import Path
from typing import Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def load_report_data(storage: BookStorage) -> Dict[int, Dict[str, Any]]:
    stage_storage = storage.stage("label-structure")
    csv_path = stage_storage.output_dir / "report.csv"

    report_data = {}
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            page_num = int(row['page_num'])
            report_data[page_num] = row

    return report_data


def get_context_pages(cluster: Dict[str, Any], report_data: Dict[int, Dict[str, Any]], context_size: int = 3) -> List[Dict[str, Any]]:
    scan_pages = cluster['scan_pages']
    min_page = min(scan_pages)
    max_page = max(scan_pages)

    start_page = max(1, min_page - context_size)
    end_page = max_page + context_size

    context = []
    for page_num in range(start_page, end_page + 1):
        if page_num in report_data:
            row = report_data[page_num].copy()
            row['page_num'] = int(row['page_num'])
            row['in_cluster'] = page_num in scan_pages
            context.append(row)

    return context


def generate_cluster_html(
    storage: BookStorage,
    logger: PipelineLogger,
) -> str:
    stage_storage = storage.stage("label-structure")
    clusters_path = stage_storage.output_dir / "clusters.json"

    if not clusters_path.exists():
        logger.error("clusters.json not found - run clustering first")
        return ""

    with open(clusters_path, 'r') as f:
        cluster_data = json.load(f)

    report_data = load_report_data(storage)

    clusters = sorted(cluster_data['clusters'], key=lambda c: min(c['scan_pages']))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{storage.scan_id} - Gap Healing Clusters</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 2rem;
            background: #f5f5f5;
        }}

        .header {{
            background: white;
            padding: 2rem;
            margin-bottom: 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        h1 {{
            margin: 0 0 1rem 0;
            color: #333;
        }}

        .summary {{
            display: flex;
            gap: 2rem;
            margin-top: 1rem;
        }}

        .summary-item {{
            display: flex;
            flex-direction: column;
        }}

        .summary-label {{
            font-size: 0.85rem;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .summary-value {{
            font-size: 1.5rem;
            font-weight: 600;
            color: #333;
        }}

        .cluster-card {{
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .cluster-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid #e0e0e0;
        }}

        .cluster-title {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #333;
        }}

        .cluster-badge {{
            display: inline-block;
            padding: 0.3rem 0.6rem;
            border-radius: 4px;
            font-size: 0.85rem;
            font-weight: 500;
            margin-left: 0.5rem;
        }}

        .badge-backward_jump {{
            background: #ffebee;
            color: #c62828;
        }}

        .badge-ocr_error {{
            background: #fff3e0;
            color: #f57c00;
        }}

        .badge-structural_gap {{
            background: #e3f2fd;
            color: #1976d2;
        }}

        .badge-gap_mismatch {{
            background: #fce4ec;
            color: #c2185b;
        }}

        .badge-isolated {{
            background: #f3e5f5;
            color: #7b1fa2;
        }}

        .priority-high {{
            background: #ffebee;
            color: #c62828;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .priority-medium {{
            background: #fff3e0;
            color: #f57c00;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .priority-low {{
            background: #e8f5e9;
            color: #2e7d32;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .cluster-details {{
            display: flex;
            gap: 1.5rem;
            margin-bottom: 1rem;
            font-size: 0.9rem;
            color: #666;
        }}

        .cluster-details strong {{
            color: #333;
        }}

        .page-sequence {{
            margin-top: 1rem;
        }}

        .sequence-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}

        .sequence-table th {{
            background: #f5f5f5;
            padding: 0.5rem;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #e0e0e0;
        }}

        .sequence-table td {{
            padding: 0.5rem;
            border-bottom: 1px solid #f0f0f0;
        }}

        .sequence-table tr.in-cluster {{
            background: #fff9c4;
            font-weight: 600;
        }}

        .sequence-table tr.context {{
            background: white;
        }}

        .status-ok {{
            color: #2e7d32;
        }}

        .status-problem {{
            color: #c62828;
            font-weight: 600;
        }}

        .status-gap {{
            color: #f57c00;
        }}

        .status-neutral {{
            color: #666;
        }}

        .heading-text {{
            font-size: 0.85rem;
            color: #666;
            max-width: 300px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 Gap Healing Clusters: {storage.scan_id}</h1>
        <div class="summary">
            <div class="summary-item">
                <span class="summary-label">Total Clusters</span>
                <span class="summary-value">{cluster_data['total_clusters']}</span>
            </div>
            <div class="summary-item">
                <span class="summary-label">Backward Jumps</span>
                <span class="summary-value">{cluster_data['clusters_by_type'].get('backward_jump', 0)}</span>
            </div>
            <div class="summary-item">
                <span class="summary-label">OCR Errors</span>
                <span class="summary-value">{cluster_data['clusters_by_type'].get('ocr_error', 0)}</span>
            </div>
            <div class="summary-item">
                <span class="summary-label">Structural Gaps</span>
                <span class="summary-value">{cluster_data['clusters_by_type'].get('structural_gap', 0)}</span>
            </div>
        </div>
    </div>
"""

    for cluster in clusters:
        cluster_type = cluster['type']
        cluster_id = cluster['cluster_id']
        priority = cluster['priority']

        html += f"""
    <div class="cluster-card">
        <div class="cluster-header">
            <div>
                <span class="cluster-title">{cluster_id}</span>
                <span class="cluster-badge badge-{cluster_type}">{cluster_type.replace('_', ' ').title()}</span>
            </div>
            <span class="priority-{priority}">{priority}</span>
        </div>

        <div class="cluster-details">
            <div>
                <strong>Pages:</strong> {', '.join(map(str, cluster['scan_pages']))}
            </div>
"""

        if cluster_type == 'backward_jump':
            html += f"""
            <div>
                <strong>Detected:</strong> {cluster.get('detected_value', 'N/A')}
            </div>
            <div>
                <strong>Expected:</strong> {cluster.get('expected_value', 'N/A')}
            </div>
"""
        elif cluster_type == 'ocr_error':
            html += f"""
            <div>
                <strong>Raw Value:</strong> {cluster.get('raw_value', 'N/A')}
            </div>
"""
        elif cluster_type == 'structural_gap':
            html += f"""
            <div>
                <strong>Gap Size:</strong> {cluster.get('gap_size', 'N/A')}
            </div>
"""

        html += """
        </div>

        <div class="page-sequence">
            <table class="sequence-table">
                <thead>
                    <tr>
                        <th>Page</th>
                        <th>Page #</th>
                        <th>Status</th>
                        <th>Gap</th>
                        <th>Expected</th>
                        <th>Headings</th>
                    </tr>
                </thead>
                <tbody>
"""

        # Add context pages
        context_pages = get_context_pages(cluster, report_data, context_size=3)
        for page_row in context_pages:
            row_class = 'in-cluster' if page_row['in_cluster'] else 'context'
            page_num = page_row['page_num']
            page_num_value = page_row.get('page_num_value', '—')
            status = page_row.get('sequence_status', 'unknown')
            gap = page_row.get('sequence_gap', '0')
            expected = page_row.get('expected_value', '—')
            headings = page_row.get('headings_text', '')

            if status == 'ok':
                status_class = 'status-ok'
                status_text = '✓ OK'
            elif status == 'backward_jump':
                status_class = 'status-problem'
                status_text = '⚠ Backward'
            elif status == 'unparseable':
                status_class = 'status-problem'
                status_text = '⚠ Bad format'
            elif status.startswith('gap_'):
                status_class = 'status-gap'
                status_text = f'Gap {status[4:]}'
            elif status == 'no_number':
                status_class = 'status-neutral'
                status_text = 'No #'
            else:
                status_class = 'status-neutral'
                status_text = status.replace('_', ' ').title()

            html += f"""
                    <tr class="{row_class}">
                        <td><strong>{page_num}</strong></td>
                        <td>{page_num_value}</td>
                        <td class="{status_class}">{status_text}</td>
                        <td>{gap}</td>
                        <td>{expected}</td>
                        <td><span class="heading-text">{headings if headings else '—'}</span></td>
                    </tr>
"""

        html += """
                </tbody>
            </table>
        </div>
    </div>
"""

    html += """
</body>
</html>
"""

    output_path = stage_storage.output_dir / "clusters_visualization.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    logger.info(f"Cluster visualization saved: {output_path}")

    embeddable_html = f"""
<style>
    .cluster-header {{
        background: white;
        padding: 2rem;
        margin-bottom: 2rem;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }}

    .cluster-header h1 {{
        margin: 0 0 1rem 0;
        color: #333;
    }}

    .summary {{
        display: flex;
        gap: 2rem;
        margin-top: 1rem;
    }}

    .summary-item {{
        display: flex;
        flex-direction: column;
    }}

    .summary-label {{
        font-size: 0.85rem;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    .summary-value {{
        font-size: 1.5rem;
        font-weight: 600;
        color: #333;
    }}

    .cluster-card {{
        background: white;
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 2rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }}

    .cluster-header-inner {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
        padding-bottom: 1rem;
        border-bottom: 2px solid #e0e0e0;
    }}

    .cluster-title {{
        font-size: 1.1rem;
        font-weight: 600;
        color: #333;
    }}

    .cluster-badge {{
        display: inline-block;
        padding: 0.3rem 0.6rem;
        border-radius: 4px;
        font-size: 0.85rem;
        font-weight: 500;
        margin-left: 0.5rem;
    }}

    .badge-backward_jump {{
        background: #ffebee;
        color: #c62828;
    }}

    .badge-ocr_error {{
        background: #fff3e0;
        color: #f57c00;
    }}

    .badge-structural_gap {{
        background: #e3f2fd;
        color: #1976d2;
    }}

    .badge-gap_mismatch {{
        background: #fce4ec;
        color: #c2185b;
    }}

    .badge-isolated {{
        background: #f3e5f5;
        color: #7b1fa2;
    }}

    .priority-high {{
        background: #ffebee;
        color: #c62828;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
    }}

    .priority-medium {{
        background: #fff3e0;
        color: #f57c00;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
    }}

    .priority-low {{
        background: #e8f5e9;
        color: #2e7d32;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
    }}

    .cluster-details {{
        display: flex;
        gap: 1.5rem;
        margin-bottom: 1rem;
        font-size: 0.9rem;
        color: #666;
    }}

    .cluster-details strong {{
        color: #333;
    }}

    .page-sequence {{
        margin-top: 1rem;
    }}

    .sequence-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.9rem;
    }}

    .sequence-table th {{
        background: #f5f5f5;
        padding: 0.5rem;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #e0e0e0;
    }}

    .sequence-table td {{
        padding: 0.5rem;
        border-bottom: 1px solid #f0f0f0;
    }}

    .sequence-table tr.in-cluster {{
        background: #fff9c4;
        font-weight: 600;
    }}

    .sequence-table tr.context {{
        background: white;
    }}

    .status-ok {{
        color: #2e7d32;
    }}

    .status-problem {{
        color: #c62828;
        font-weight: 600;
    }}

    .status-gap {{
        color: #f57c00;
    }}

    .status-neutral {{
        color: #666;
    }}

    .heading-text {{
        font-size: 0.85rem;
        color: #666;
        max-width: 300px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
</style>

<div class="cluster-header">
    <h1>🔍 Gap Healing Clusters: {storage.scan_id}</h1>
    <div class="summary">
        <div class="summary-item">
            <span class="summary-label">Total Clusters</span>
            <span class="summary-value">{cluster_data['total_clusters']}</span>
        </div>
        <div class="summary-item">
            <span class="summary-label">Backward Jumps</span>
            <span class="summary-value">{cluster_data['clusters_by_type'].get('backward_jump', 0)}</span>
        </div>
        <div class="summary-item">
            <span class="summary-label">OCR Errors</span>
            <span class="summary-value">{cluster_data['clusters_by_type'].get('ocr_error', 0)}</span>
        </div>
        <div class="summary-item">
            <span class="summary-label">Structural Gaps</span>
            <span class="summary-value">{cluster_data['clusters_by_type'].get('structural_gap', 0)}</span>
        </div>
    </div>
</div>
"""

    # Add cluster cards (same as before but with updated class name for header)
    for cluster in clusters:
        cluster_type = cluster['type']
        cluster_id = cluster['cluster_id']
        priority = cluster['priority']

        embeddable_html += f"""
<div class="cluster-card">
    <div class="cluster-header-inner">
        <div>
            <span class="cluster-title">{cluster_id}</span>
            <span class="cluster-badge badge-{cluster_type}">{cluster_type.replace('_', ' ').title()}</span>
        </div>
        <span class="priority-{priority}">{priority}</span>
    </div>

    <div class="cluster-details">
        <div>
            <strong>Pages:</strong> {', '.join(map(str, cluster['scan_pages']))}
        </div>
"""

        if cluster_type == 'backward_jump':
            embeddable_html += f"""
        <div>
            <strong>Detected:</strong> {cluster.get('detected_value', 'N/A')}
        </div>
        <div>
            <strong>Expected:</strong> {cluster.get('expected_value', 'N/A')}
        </div>
"""
        elif cluster_type == 'ocr_error':
            embeddable_html += f"""
        <div>
            <strong>Raw Value:</strong> {cluster.get('raw_value', 'N/A')}
        </div>
"""
        elif cluster_type == 'structural_gap':
            embeddable_html += f"""
        <div>
            <strong>Gap Size:</strong> {cluster.get('gap_size', 'N/A')}
        </div>
"""

        embeddable_html += """
    </div>

    <div class="page-sequence">
        <table class="sequence-table">
            <thead>
                <tr>
                    <th>Page</th>
                    <th>Page #</th>
                    <th>Status</th>
                    <th>Gap</th>
                    <th>Expected</th>
                    <th>Headings</th>
                </tr>
            </thead>
            <tbody>
"""

        # Add context pages
        context_pages = get_context_pages(cluster, report_data, context_size=3)
        for page_row in context_pages:
            row_class = 'in-cluster' if page_row['in_cluster'] else 'context'
            page_num = page_row['page_num']
            page_num_value = page_row.get('page_num_value', '—')
            status = page_row.get('sequence_status', 'unknown')
            gap = page_row.get('sequence_gap', '0')
            expected = page_row.get('expected_value', '—')
            headings = page_row.get('headings_text', '')

            if status == 'ok':
                status_class = 'status-ok'
                status_text = '✓ OK'
            elif status == 'backward_jump':
                status_class = 'status-problem'
                status_text = '⚠ Backward'
            elif status == 'unparseable':
                status_class = 'status-problem'
                status_text = '⚠ Bad format'
            elif status.startswith('gap_'):
                status_class = 'status-gap'
                status_text = f'Gap {status[4:]}'
            elif status == 'no_number':
                status_class = 'status-neutral'
                status_text = 'No #'
            else:
                status_class = 'status-neutral'
                status_text = status.replace('_', ' ').title()

            embeddable_html += f"""
                <tr class="{row_class}">
                    <td><strong>{page_num}</strong></td>
                    <td>{page_num_value}</td>
                    <td class="{status_class}">{status_text}</td>
                    <td>{gap}</td>
                    <td>{expected}</td>
                    <td><span class="heading-text">{headings if headings else '—'}</span></td>
                </tr>
"""

        embeddable_html += """
            </tbody>
        </table>
    </div>
</div>
"""

    embeddable_path = stage_storage.output_dir / "clusters_embeddable.html"
    with open(embeddable_path, 'w', encoding='utf-8') as f:
        f.write(embeddable_html)

    return str(output_path)
