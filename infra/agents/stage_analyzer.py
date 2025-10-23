#!/usr/bin/env python3
"""
Stage Analyzer - Lightweight agent for analyzing pipeline stage outputs.

Uses OpenRouter tool calling via LLMClient for cost tracking and model selection.
Stages customize behavior by defining static analyze() methods.
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import json
import hashlib
from datetime import datetime

from infra.llm.client import LLMClient
from infra.storage.book_storage import BookStorage
from infra.config import Config
from infra.agents.python_sandbox import execute_code_safely


class StageAnalyzer:
    """
    Lightweight agent for stage analysis using OpenRouter tool calling.

    Features:
    - Uses existing LLMClient (OpenRouter key, cost tracking)
    - Tool calling for filesystem access (read reports, load pages)
    - Iterative analysis loop until agent writes final report
    - Tracks cost and iterations

    Usage:
        analyzer = StageAnalyzer(storage, 'labels')
        result = analyzer.analyze()
    """

    def __init__(
        self,
        storage: BookStorage,
        stage_name: str,
        model: str = None,
        max_iterations: int = 25
    ):
        """
        Initialize analyzer for a specific stage.

        Args:
            storage: BookStorage instance for the book
            stage_name: Name of stage to analyze (e.g., 'labels', 'corrected')
            model: OpenRouter model (default: Config.text_model_primary)
            max_iterations: Max agent loop iterations
        """
        self.storage = storage
        self.stage_name = stage_name
        self.model = model or Config.text_model_primary
        self.max_iterations = max_iterations

        # Use existing LLM client (cost tracking built-in)
        self.llm_client = LLMClient()

        # Track agent execution
        self.total_cost = 0.0
        self.iterations = 0
        self.analysis_path = None
        self.tool_calls_log = []  # Store all tool calls for logging

        # Setup agent directory
        self.agent_dir = self.storage.stage(self.stage_name).output_dir / "agent"
        self.agent_dir.mkdir(exist_ok=True)

    def _build_tool_definitions(self) -> List[Dict]:
        """
        Build OpenRouter tool definitions in JSON Schema format.

        Returns list of tool definitions for OpenRouter API.
        See: https://openrouter.ai/docs/features/tool-calling
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_report",
                    "description": "Read the stage's report.csv file and return formatted summary with statistics",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "load_page_data",
                    "description": "Load all data for a specific page including stage output, OCR data, and source image availability",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Page number to load (1-indexed)"
                            }
                        },
                        "required": ["page_num"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_problematic_pages",
                    "description": "List page numbers that match specific quality criteria from the report",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "criteria": {
                                "type": "string",
                                "description": "Description of what to look for (e.g., 'low confidence', 'missing page numbers')"
                            }
                        },
                        "required": ["criteria"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_python",
                    "description": "Execute Python code in a sandboxed environment. IMPORTANT: pandas is pre-imported as 'pd', matplotlib.pyplot as 'plt', json, and Path are available. DO NOT use import statements - they will fail. Variables: stage_dir (Path), report_path (Path to report.csv), viz_dir (Path for saving plots). Use print() to output results. For plots: plt.savefig(viz_dir / 'name.png')",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute. DO NOT use import statements. Example: 'df = pd.read_csv(report_path); print(df.describe())' or 'df = pd.read_csv(report_path); plt.hist(df[\"confidence\"]); plt.savefig(viz_dir / \"confidence_hist.png\"); print(\"Saved plot\")'"
                            }
                        },
                        "required": ["code"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_analysis",
                    "description": "Write the final analysis report to a markdown file in the stage directory. Call this when analysis is complete.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Full analysis content in markdown format with findings and recommendations"
                            }
                        },
                        "required": ["content"]
                    }
                }
            }
        ]

    def _get_stage_specific_guidance(self) -> str:
        """Return stage-specific analysis guidance."""
        if self.stage_name == 'corrected':
            return """**Correction Stage Focus:**
Analyze OCR correction quality. Key metrics in report.csv:
- total_corrections: Number of paragraphs corrected per page
- avg_confidence: Correction certainty (target: >0.90)
- text_similarity_ratio: How much text changed (1.0=no changes, <0.80=major rewrites)
- characters_changed: Edit magnitude

IMPORTANT: Low similarity does NOT indicate problems. It often represents CORRECT large-scale fixes.

Critical Issues to Identify (use confidence as PRIMARY signal):
- Low confidence pages (avg_confidence <0.85): These genuinely need review
- Combined red flags (avg_confidence <0.92 AND text_similarity_ratio <0.70): Worth checking
- Inconsistent confidence: High variance across pages (suggests prompt/model issues)

Expected Patterns (THESE ARE CORRECT, NOT PROBLEMS):
- "Short block pattern": Few corrections + large character changes + low similarity (<0.80) + high confidence (>0.95)
  → This is CORRECT behavior - agent fixed heavily corrupted blocks (titles, headers, line-break hyphens)
- High confidence (>0.95) + Low similarity (<0.80): Often legitimate structural fixes, NOT over-correction
- Most pages should have avg_confidence >0.95

Pages to Flag:
- Primary: avg_confidence < 0.85 (genuine uncertainty, ~1-2% of pages)
- Secondary: avg_confidence < 0.92 AND text_similarity_ratio < 0.70 (double-check only)
- DO NOT flag pages solely on low similarity - this creates 70-95% false positives

NOTE: Cost tracking is handled separately by the pipeline - do NOT calculate costs from JSON files."""

        elif self.stage_name == 'labels':
            return """**Label Stage Focus:**
Analyze page number extraction and block classification. Key metrics:
- page_number_extracted: Whether a page number was found
- printed_page_number: The extracted number (if found)
- avg_classification_confidence: Block classification certainty
- page_region: Front matter, body, or back matter classification
- block_count: Number of structural blocks per page

IMPORTANT: "Missing" page numbers are often CORRECT - books legitimately have unnumbered pages.

Critical Issues to Identify (use context, not raw metrics):
- Duplicate printed_page_number values (OCR confusion or legitimate book structure)
- Systematic extraction failures (>20% in body section with no explanation)
- Wrong page_region classification (verify against numbering patterns)
- Very low confidence (<0.80) without corresponding high block_count

Expected Patterns (THESE ARE CORRECT, NOT PROBLEMS):
- Front matter "failures" (80-95%): Title pages, TOC, dedications are legitimately unnumbered
- Chapter openings "failures" (common): Decorative chapter starts often lack page numbers
- Illustration/photo pages "failures" (common): Full-page images often unnumbered
- Low confidence (0.85-0.92) + High block_count (10+): Complex layouts (endnotes, indices) - appropriate
- Back matter "failures" (10-30%): Index dividers, appendix sections often unnumbered

Pages to Flag:
- Primary: Duplicate printed_page_number in body section (verify if legitimate or OCR error)
- Secondary: page_number_extracted=False in body section with no structural justification
- Tertiary: avg_classification_confidence < 0.80 without high block_count explanation
- DO NOT flag pages solely on "missing" page numbers - this creates 85% false positives

Region Classification (100% Trustworthy):
- Use page_region as validation metric - it's consistently accurate
- Front matter should have roman numerals or no numbers
- Body should have sequential arabic numerals
- Back matter may have continued numbering or independent sequences

NOTE: Cost tracking is handled separately by the pipeline - do NOT calculate costs from JSON files."""

        else:
            # Generic guidance for other stages
            return f"""**{self.stage_name.title()} Stage Analysis:**
Examine the report.csv metrics to identify quality issues, patterns, and pages needing review.

NOTE: Cost tracking is handled separately by the pipeline - do NOT calculate costs from JSON files."""

    def _execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool and return result as string."""

        if tool_name == "read_report":
            return self._read_report()

        elif tool_name == "load_page_data":
            return self._load_page_data(arguments["page_num"])

        elif tool_name == "list_problematic_pages":
            return self._list_problematic_pages(arguments["criteria"])

        elif tool_name == "execute_python":
            return self._execute_python(arguments["code"])

        elif tool_name == "write_analysis":
            return self._write_analysis(arguments["content"])

        else:
            return f"Error: Unknown tool '{tool_name}'"

    def _read_report(self) -> str:
        """Read the stage's report.csv and return as formatted string."""
        try:
            import pandas as pd
        except ImportError:
            return "Error: pandas not installed. Install with: uv pip install pandas"

        stage_dir = self.storage.stage(self.stage_name).output_dir
        report_path = stage_dir / "report.csv"

        if not report_path.exists():
            return f"Error: No report.csv found at {report_path}"

        try:
            df = pd.read_csv(report_path)

            # Return formatted summary (truncate for context limits)
            max_rows = 1000
            summary = f"""Report Summary:
Total pages: {len(df)}
Columns: {', '.join(df.columns)}

First 10 rows:
{df.head(10).to_string()}

Statistics:
{df.describe().to_string()}

Full data ({min(len(df), max_rows)} of {len(df)} rows):
{df.head(max_rows).to_string()}
"""
            return summary
        except Exception as e:
            return f"Error reading report: {e}"

    def _load_page_data(self, page_num: int) -> str:
        """Load all data for a specific page (source, OCR, stage output)."""
        result = {
            'page_num': page_num,
            'stage_output': None,
            'source_available': False,
            'ocr_data': None,
        }

        try:
            # Load stage output
            stage_storage = self.storage.stage(self.stage_name)
            page_file = stage_storage.output_page(page_num, extension='json')
            if page_file.exists():
                with open(page_file) as f:
                    result['stage_output'] = json.load(f)

            # Check source image
            source_file = self.storage.stage('source').output_page(page_num, extension='png')
            result['source_available'] = source_file.exists()
            result['source_path'] = str(source_file) if source_file.exists() else None

            # Load OCR if available
            ocr_file = self.storage.stage('ocr').output_page(page_num, extension='json')
            if ocr_file.exists():
                with open(ocr_file) as f:
                    result['ocr_data'] = json.load(f)

            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error loading page {page_num}: {e}"

    def _list_problematic_pages(self, criteria: str) -> str:
        """
        List pages matching criteria based on report.csv.

        Args:
            criteria: Description of what to look for
        """
        try:
            import pandas as pd
        except ImportError:
            return "Error: pandas not installed"

        stage_dir = self.storage.stage(self.stage_name).output_dir
        report_path = stage_dir / "report.csv"

        if not report_path.exists():
            return "Error: No report.csv found"

        try:
            df = pd.read_csv(report_path)

            # Simple heuristic-based filtering
            problematic = []

            if 'confidence' in criteria.lower():
                # Check for confidence columns
                conf_cols = [col for col in df.columns if 'confidence' in col.lower()]
                for col in conf_cols:
                    low_conf = df[df[col] < 0.7]
                    problematic.extend(low_conf['page_num'].tolist())

            if 'missing' in criteria.lower() and 'page' in criteria.lower():
                # Check for boolean columns about page numbers
                if 'page_number_extracted' in df.columns:
                    missing = df[df['page_number_extracted'] == False]
                    problematic.extend(missing['page_num'].tolist())

            if 'region' in criteria.lower():
                # Check for region-related columns
                if 'page_region_classified' in df.columns:
                    unclassified = df[df['page_region_classified'] == False]
                    problematic.extend(unclassified['page_num'].tolist())

            unique_pages = sorted(set(problematic))

            return f"""Pages matching criteria '{criteria}':
Total: {len(unique_pages)}
Page numbers: {unique_pages[:50]}  {'...' if len(unique_pages) > 50 else ''}
"""
        except Exception as e:
            return f"Error analyzing criteria: {e}"

    def _execute_python(self, code: str) -> str:
        """
        Execute Python code in sandboxed environment with access to stage data.

        Delegates to python_sandbox.execute_code_safely() for secure execution.
        """
        stage_dir = self.storage.stage(self.stage_name).output_dir
        report_path = stage_dir / "report.csv"

        return execute_code_safely(code, stage_dir, report_path)

    def _generate_run_hash(self, focus_areas: Optional[List[str]] = None) -> str:
        """Generate hash for this analysis run based on stage, model, and focus."""
        hash_input = f"{self.stage_name}:{self.model}"
        if focus_areas:
            hash_input += f":{','.join(sorted(focus_areas))}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:8]

    def _log_tool_call(self, iteration: int, tool_name: str, arguments: Dict, result: str, execution_time: float):
        """Log tool call to internal buffer."""
        self.tool_calls_log.append({
            'iteration': iteration,
            'tool_name': tool_name,
            'arguments': arguments,
            'result': result[:500],  # Truncate long results
            'execution_time_seconds': execution_time,
            'timestamp': datetime.now().isoformat()
        })

    def _save_tool_calls(self, run_hash: str):
        """Save all tool calls to JSONL file."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        tool_calls_path = self.agent_dir / f"tool-calls-{timestamp}-{run_hash}.jsonl"

        with open(tool_calls_path, 'w') as f:
            for call in self.tool_calls_log:
                f.write(json.dumps(call) + '\n')

        return tool_calls_path

    def _write_analysis(self, content: str) -> str:
        """Write analysis report to agent directory with hash."""
        try:
            # This will be called from tool, so we need to finalize after
            self._pending_analysis_content = content
            return "✅ Analysis ready to save"
        except Exception as e:
            return f"Error preparing analysis: {e}"

    def analyze(self, focus_areas: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Run analysis agent loop using OpenRouter tool calling.

        Args:
            focus_areas: Optional list of specific areas to focus on

        Returns:
            Dict with analysis_path, cost_usd, iterations, model, tool_calls_path
        """
        import time

        # Generate hash for this run
        run_hash = self._generate_run_hash(focus_areas)

        # Build system prompt with stage-specific guidance
        stage_specific_guidance = self._get_stage_specific_guidance()

        system_prompt = f"""You are analyzing the {self.stage_name} stage output for a book scanning pipeline.

{stage_specific_guidance}

Your task:
1. Call read_report() to understand the overall quality metrics
2. Use execute_python() to run statistical analysis on the data:
   - Calculate distributions, correlations, percentiles
   - Find complex patterns across multiple columns
   - Aggregate statistics across all JSON files
   - IMPORTANT: pandas is pre-imported as 'pd', matplotlib.pyplot as 'plt'. DO NOT use import statements.
   - Example: execute_python("df = pd.read_csv(report_path); print(df['avg_classification_confidence'].describe())")
3. Create visualizations using matplotlib (available as plt):
   - Visualizations are saved to viz_dir (automatically provided)
   - IMPORTANT: plt is already imported. DO NOT use import statements.
   - Example: execute_python("df = pd.read_csv(report_path); plt.figure(); df['confidence'].hist(); plt.savefig(viz_dir / 'confidence_dist.png'); print('Saved confidence_dist.png')")
   - Useful for: distributions, trends, correlations, patterns
4. Call list_problematic_pages() or execute_python() to find pages with issues
5. Call load_page_data() for 5-10 problematic pages to examine root causes
6. Analyze patterns and identify systematic vs. isolated issues
7. Call write_analysis() with markdown report following this template:

```markdown
# {{Stage Name}} Analysis - {{scan_id}}

**Quality Score:** {{X}}/100 | **Pages:** {{N}} | **Cost:** ${{X.XX}}

## Executive Summary
[2-3 sentences: overall quality, critical issues, recommended action]

## Statistics
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| [Key metric] | X.XX | X.XX | ✓/✗ |

![Visualization](viz/chart.png) (if created)

## Critical Issues
**{{Issue Name}}** - {{N}} pages ({{X}}%)
- Pages: 12, 34, 56
- Root cause: [systematic/isolated + why]
- Impact: [downstream effect]
- Fix: [action + effort estimate]

## High/Medium Priority
[Same format, briefer]

## Recommendations
1. **P1**: {{Action}} - {{pages/stage}} - {{effort}}
2. **P2**: {{Action}} - {{effort}}

## Appendix
**Sample Pages:** {{num}}, {{num}}, {{num}} showing {{issue}}

**Terms:** Critical=blocking, High=significant, Medium=noticeable, Low=cosmetic
```

Keep report concise. Use specific page numbers. Include quality score.

Python Sandbox Constraints:
- pandas is pre-imported as 'pd', matplotlib.pyplot as 'plt', json, and Path are available
- DO NOT use import statements (will cause ImportError)
- Use print() to output results
- For plots: plt.savefig(viz_dir / 'filename.png')

Be specific and include page numbers in all findings. Use execute_python() for any statistical analysis beyond simple queries."""

        user_prompt = f"Analyze the {self.stage_name} stage for quality issues."
        if focus_areas:
            user_prompt += f"\n\nFocus specifically on: {', '.join(focus_areas)}"

        # Initialize conversation
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Tool definitions
        tools = self._build_tool_definitions()

        # Agent loop with OpenRouter tool calling
        for iteration in range(self.max_iterations):
            self.iterations = iteration + 1

            # Concise progress
            print(f"Iteration {self.iterations}: Thinking...", end='', flush=True)

            # Call LLM with tools
            content, usage, cost, tool_calls = self.llm_client.call_with_tools(
                model=self.model,
                messages=messages,
                tools=tools,
                temperature=0.0
            )

            self.total_cost += cost
            print(f" (${cost:.3f})")

            # Build assistant message
            assistant_msg = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls

            messages.append(assistant_msg)

            # If no tool calls, agent is done or stuck
            if not tool_calls:
                if self.analysis_path:
                    # Agent finished successfully
                    break
                else:
                    # Agent didn't call tools - prompt to continue
                    messages.append({
                        "role": "user",
                        "content": "Please use the available tools to complete your analysis."
                    })
                    continue

            # Execute tool calls and add results
            for tool_call in tool_calls:
                tool_name = tool_call['function']['name']

                # Parse arguments (they come as JSON string)
                try:
                    arguments = json.loads(tool_call['function']['arguments'])
                except json.JSONDecodeError:
                    arguments = {}

                # Concise tool execution log
                arg_preview = str(arguments)[:40]
                if len(str(arguments)) > 40:
                    arg_preview += "..."
                print(f"  → {tool_name}({arg_preview})", end='', flush=True)

                # Execute tool and time it
                start_time = time.time()
                result = self._execute_tool(tool_name, arguments)
                execution_time = time.time() - start_time

                # Log tool call for later analysis
                self._log_tool_call(self.iterations, tool_name, arguments, result, execution_time)

                # Show completion
                if tool_name == "write_analysis":
                    print(" ✓")
                else:
                    print(f" ({execution_time:.1f}s)")

                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call['id'],
                    "content": result
                })

            # Check if analysis was written (agent is done)
            if hasattr(self, '_pending_analysis_content'):
                break

        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save tool calls log
        tool_calls_path = self._save_tool_calls(run_hash)

        # Save final analysis report
        if hasattr(self, '_pending_analysis_content'):
            # Agent completed successfully
            self.analysis_path = self.agent_dir / f"report-{timestamp}-{run_hash}.md"

            full_content = f"""# {self.stage_name.title()} Stage Analysis

**Scan ID:** {self.storage.scan_id}
**Timestamp:** {timestamp}
**Run Hash:** {run_hash}
**Model:** {self.model}
**Total Cost:** ${self.total_cost:.4f}
**Iterations:** {self.iterations}
**Tool Calls:** {len(self.tool_calls_log)}

---

{self._pending_analysis_content}
"""

            with open(self.analysis_path, 'w') as f:
                f.write(full_content)

        else:
            # Agent didn't finish
            self.analysis_path = self.agent_dir / f"report-incomplete-{timestamp}-{run_hash}.md"

            with open(self.analysis_path, 'w') as f:
                f.write(f"""# {self.stage_name.title()} Stage Analysis (INCOMPLETE)

**Scan ID:** {self.storage.scan_id}
**Timestamp:** {timestamp}
**Run Hash:** {run_hash}
**Model:** {self.model}
**Total Cost:** ${self.total_cost:.4f}
**Iterations:** {self.iterations}
**Status:** Agent did not complete within {self.max_iterations} iterations

---

The agent did not finish. Check tool-calls log for details:
{tool_calls_path}
""")

        return {
            'analysis_path': self.analysis_path,
            'tool_calls_path': tool_calls_path,
            'cost_usd': self.total_cost,
            'iterations': self.iterations,
            'model': self.model,
            'run_hash': run_hash
        }
