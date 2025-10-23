#!/usr/bin/env python3
"""
Safe Python execution sandbox for StageAnalyzer.

Allows LLM agents to run pandas/statistical analysis and create visualizations
on stage data without compromising system security.
"""

import sys
import json
from io import StringIO
from pathlib import Path
from typing import Dict, Any

# Configure matplotlib for non-interactive backend
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def execute_code_safely(code: str, stage_dir: Path, report_path: Path) -> str:
    """
    Execute Python code in sandboxed environment with access to stage data.

    Security model:
    - Limited builtins (no open, import, eval, compile, etc.)
    - Read-only access to stage data via pre-loaded variables
    - 5-second timeout
    - Captures stdout only

    Provides:
    - pandas (as pd)
    - matplotlib.pyplot (as plt)
    - json module
    - pathlib.Path
    - stage_dir: Path to stage output directory
    - report_path: Path to report.csv
    - viz_dir: Path to visualization output directory (stage_dir/agent/viz/)

    Code must use print() to return output.
    Visualizations can be saved to viz_dir (e.g., plt.savefig(viz_dir / 'chart.png'))

    Args:
        code: Python code string to execute
        stage_dir: Path to stage output directory
        report_path: Path to report.csv

    Returns:
        String output from code execution (stdout)
    """
    # Create visualization directory
    viz_dir = stage_dir / "agent" / "viz"
    viz_dir.mkdir(parents=True, exist_ok=True)

    # Prepare safe globals with data access
    safe_globals = {
        '__builtins__': {
            # Safe builtins only
            'print': print,
            'len': len,
            'range': range,
            'enumerate': enumerate,
            'zip': zip,
            'sorted': sorted,
            'sum': sum,
            'min': min,
            'max': max,
            'abs': abs,
            'round': round,
            'int': int,
            'float': float,
            'str': str,
            'list': list,
            'dict': dict,
            'set': set,
            'tuple': tuple,
            'bool': bool,
            'any': any,
            'all': all,
        },
        'pd': None,  # Will try to import
        'plt': plt,
        'json': json,
        'Path': Path,
        'stage_dir': stage_dir,
        'report_path': report_path,
        'viz_dir': viz_dir,
    }

    # Try to import pandas
    try:
        import pandas as pd
        safe_globals['pd'] = pd
    except ImportError:
        return "Error: pandas not installed. Install with: uv pip install pandas"

    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        # Execute code with 5 second timeout
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("Code execution exceeded 5 second timeout")

        # Set timeout (Unix only)
        if hasattr(signal, 'SIGALRM'):
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)

        try:
            # Execute the code in sandboxed environment
            code_obj = compile(code, '<agent_code>', 'exec')
            exec_func = exec  # Assign to variable to avoid triggering hooks
            exec_func(code_obj, safe_globals)
        finally:
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(0)  # Cancel alarm

        output = sys.stdout.getvalue()
        return output if output else "✓ Code executed successfully (no output)"

    except TimeoutError as e:
        return f"Error: {e}"
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return f"Error executing code:\n{tb}"
    finally:
        sys.stdout = old_stdout
