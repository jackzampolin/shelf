# Agent Client Design Document

## Executive Summary

This document proposes creating `infra/llm/agent_client.py` to provide reusable infrastructure for agent implementations, following the pattern established by `LLMBatchClient`. The goal is to eliminate code duplication across `StageAnalyzer` and `TocFinderAgent` while providing a consistent, battle-tested foundation for future agents.

**Key Benefits:**
- Eliminates ~200 lines of duplicated code per agent
- Provides standardized tool call logging, cost tracking, and iteration management
- Creates a clear separation between agent logic (prompts, tools) and infrastructure (loop, logging, telemetry)
- Enables consistent debugging and observability across all agents

---

## Current Duplication Analysis

### Repeated Patterns in Both Agents

Both `StageAnalyzer` and `TocFinderAgent` implement identical infrastructure:

1. **Tool Call Logging** (identical implementations):
   - `_log_tool_call()` - Records iteration, tool name, arguments, result, timing
   - `_save_tool_calls()` - Writes JSONL file with all tool calls
   - `tool_calls_log` - List buffer for storing calls

2. **Iteration Tracking**:
   - `iterations` counter
   - `max_iterations` limit
   - Loop termination logic

3. **Cost Tracking**:
   - `total_cost` accumulator
   - Per-iteration cost tracking (`iteration_costs` in StageAnalyzer)
   - Integration with `LLMClient.call_with_tools()`

4. **Agent Loop Pattern**:
   - Initialize conversation with system/user prompts
   - Iterate up to max_iterations
   - Call LLM with tools
   - Execute tool calls
   - Add results to conversation
   - Terminate on special tool call (write_analysis, write_toc_result)

5. **Error Handling**:
   - Try/catch around entire loop
   - Save partial results on error
   - Log failures

### Differences (Agent-Specific Logic)

These should **stay in individual agents**:

- **Tool Definitions**: Each agent defines its own tools (analysis vs. ToC search)
- **Prompts**: System/user prompts are domain-specific
- **Progress Display**: StageAnalyzer uses Rich Live, TocFinder uses simple prints
- **Result Storage**: Different schemas (analysis markdown vs. PageRange)
- **Tool Execution**: Different tool implementation classes (execute_tool delegates)

---

## LLMBatchClient Patterns to Adopt

### What Works Well in Batch Client

1. **Event System** (`on_event`, `on_result` callbacks):
   - Decouples core logic from progress display
   - Enables flexible progress tracking (Rich, logging, silent)
   - **Adopt for AgentClient**: Use events for tool execution, iteration progress

2. **Telemetry Tracking**:
   - Thread-safe stats accumulation
   - Detailed timing metrics (queue time, execution time, TTFT)
   - **Adopt for AgentClient**: Track tool execution time, iteration timing

3. **Logging Infrastructure**:
   - Dedicated log directory with timestamps
   - JSONL format for structured data
   - Separate files for different log types (failures, retries, internal)
   - **Adopt for AgentClient**: Tool calls JSONL, iteration log

4. **State Management**:
   - Clear separation of mutable state (`_state`, `stats`)
   - Thread-safe with locks (not needed for single-threaded agents, but good pattern)
   - **Adopt for AgentClient**: Centralize agent state in client

### What Doesn't Apply to Agents

1. **Parallelization**: Agents are inherently sequential (tool calls depend on previous results)
2. **Queue-Based Retry**: Agents use simple iteration loop, not request queue
3. **Rate Limiting**: Single-threaded agents don't need token bucket

---

## Proposed AgentClient API

### Core Design Principles

1. **Separation of Concerns**:
   - **AgentClient**: Infrastructure (loop, logging, telemetry, events)
   - **Agent Implementation**: Domain logic (tools, prompts, result storage)

2. **Event-Driven Progress**:
   - Callbacks for iteration start/end, tool execution, completion
   - Agents can plug in custom progress displays (Rich, logging, silent)

3. **Minimal Interface**:
   - Agents provide: tools, prompts, termination check
   - Client handles: loop, cost tracking, logging, error handling

### Class Definition

```python
class AgentClient:
    """
    Reusable infrastructure for tool-calling agents.

    Provides:
    - Tool-calling loop with iteration limit
    - Cost tracking and telemetry
    - Tool call logging to JSONL
    - Event-driven progress tracking
    - Error handling and partial result recovery

    Usage:
        client = AgentClient(
            max_iterations=25,
            log_dir=Path("logs/agent"),
            log_timestamp="20250124_120530"
        )

        result = client.run(
            llm_client=llm_client,
            model="anthropic/claude-sonnet-4",
            initial_messages=[...],
            tools=[...],
            execute_tool=my_tool_executor,
            is_complete=lambda msgs: check_termination(msgs),
            on_event=my_event_handler
        )
    """

    def __init__(
        self,
        max_iterations: int = 25,
        log_dir: Optional[Path] = None,
        log_timestamp: Optional[str] = None,
        verbose: bool = True
    ):
        """
        Initialize agent infrastructure.

        Args:
            max_iterations: Maximum agent loop iterations
            log_dir: Directory for tool call logs (JSONL)
            log_timestamp: Timestamp for log filenames (default: auto-generate)
            verbose: Enable progress output (default: True)
        """
```

### Main Run Method

```python
def run(
    self,
    llm_client: LLMClient,
    model: str,
    initial_messages: List[Dict],
    tools: List[Dict],
    execute_tool: Callable[[str, Dict], str],
    is_complete: Callable[[List[Dict]], bool],
    on_event: Optional[Callable[[AgentEvent], None]] = None,
    temperature: float = 0.0
) -> AgentResult:
    """
    Run agent loop until completion or max iterations.

    Args:
        llm_client: LLMClient instance for API calls
        model: OpenRouter model name
        initial_messages: Starting conversation (system + user prompts)
        tools: OpenRouter tool definitions
        execute_tool: Function to execute tool calls
            Signature: (tool_name: str, arguments: Dict) -> str
        is_complete: Function to check if agent is done
            Signature: (messages: List[Dict]) -> bool
            Called after each LLM response
        on_event: Optional callback for progress events
        temperature: LLM temperature (default: 0.0)

    Returns:
        AgentResult with:
            - success: bool
            - iterations: int
            - total_cost_usd: float
            - messages: List[Dict] (full conversation)
            - tool_calls_log: List[Dict] (all tool calls)
            - tool_calls_path: Optional[Path] (JSONL log file)
            - error: Optional[str] (if failed)
    """
```

### Event System

```python
class AgentEventType(str, Enum):
    """Agent lifecycle events."""
    ITERATION_START = "iteration_start"
    LLM_CALL = "llm_call"
    TOOL_EXECUTION = "tool_execution"
    ITERATION_END = "iteration_end"
    COMPLETED = "completed"
    ERROR = "error"


class AgentEvent(BaseModel):
    """Agent event data."""
    event_type: AgentEventType
    timestamp: float
    iteration: int

    # LLM call metrics (for LLM_CALL event)
    llm_cost_usd: Optional[float] = None
    llm_tokens: Optional[int] = None

    # Tool execution metrics (for TOOL_EXECUTION event)
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict] = None
    tool_result_preview: Optional[str] = None  # First 100 chars
    tool_execution_time: Optional[float] = None

    # Cumulative stats (for all events)
    total_cost_usd: Optional[float] = None
    total_iterations: Optional[int] = None


class AgentResult(BaseModel):
    """Agent execution result."""
    success: bool
    iterations: int
    total_cost_usd: float
    messages: List[Dict]  # Full conversation
    tool_calls_log: List[Dict]  # Detailed tool call log
    tool_calls_path: Optional[Path] = None  # JSONL log file
    error: Optional[str] = None  # If failed
    metadata: Dict[str, Any] = {}  # Agent-specific data
```

### Internal Methods

```python
def _log_tool_call(
    self,
    iteration: int,
    tool_name: str,
    arguments: Dict,
    result: str,
    execution_time: float
):
    """Log tool call to internal buffer."""

def _save_tool_calls(self) -> Path:
    """Save all tool calls to JSONL file."""

def _emit_event(self, event: AgentEvent):
    """Emit event to callback if configured."""
```

---

## Before/After Code Examples

### Before: StageAnalyzer (Current Implementation)

```python
class StageAnalyzer:
    def __init__(self, storage, stage_name, model=None, max_iterations=25):
        self.storage = storage
        self.stage_name = stage_name
        self.model = model or Config.text_model_primary
        self.max_iterations = max_iterations

        self.llm_client = LLMClient()
        self.total_cost = 0.0
        self.iterations = 0
        self.tool_calls_log = []
        self.iteration_costs = []
        # ... agent setup

    def analyze(self, focus_areas=None):
        # Build prompts
        system_prompt = self._get_stage_specific_guidance()
        user_prompt = f"Analyze {self.stage_name}..."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        tools = self._build_tool_definitions()

        # Agent loop
        for iteration in range(self.max_iterations):
            self.iterations = iteration + 1

            # Call LLM
            content, usage, cost, tool_calls = self.llm_client.call_with_tools(
                model=self.model,
                messages=messages,
                tools=tools,
                temperature=0.0
            )

            self.total_cost += cost
            self.iteration_costs.append(cost)

            # Build assistant message
            assistant_msg = {"role": "assistant"}
            if content:
                assistant_msg["content"] = content
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            # Check termination
            if not tool_calls:
                if self.analysis_path:
                    break
                else:
                    messages.append({
                        "role": "user",
                        "content": "Please use the available tools..."
                    })
                    continue

            # Execute tools
            for tool_call in tool_calls:
                tool_name = tool_call['function']['name']
                arguments = json.loads(tool_call['function']['arguments'])

                start_time = time.time()
                result = self._execute_tool(tool_name, arguments)
                execution_time = time.time() - start_time

                self._log_tool_call(self.iterations, tool_name, arguments, result, execution_time)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call['id'],
                    "content": result
                })

            if hasattr(self, '_pending_analysis_content'):
                break

        # Save results
        tool_calls_path = self._save_tool_calls(run_hash)
        # ... save analysis report

        return {
            'analysis_path': self.analysis_path,
            'tool_calls_path': tool_calls_path,
            'cost_usd': self.total_cost,
            'iterations': self.iterations,
            'model': self.model
        }
```

**Duplicated Code**: ~150 lines of agent loop, tool call logging, cost tracking

---

### After: StageAnalyzer (Using AgentClient)

```python
class StageAnalyzer:
    def __init__(self, storage, stage_name, model=None, max_iterations=25):
        self.storage = storage
        self.stage_name = stage_name
        self.model = model or Config.text_model_primary
        self.max_iterations = max_iterations

        self.llm_client = LLMClient()
        self.analysis_path = None
        self._pending_analysis_content = None

        # Setup agent directory
        self.agent_dir = self.storage.stage(self.stage_name).output_dir / "agent"
        self.agent_dir.mkdir(exist_ok=True)

    def analyze(self, focus_areas=None):
        # Build prompts (domain-specific)
        system_prompt = self._get_stage_specific_guidance()
        user_prompt = f"Analyze {self.stage_name}..."

        initial_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Build tools (domain-specific)
        tools = self._build_tool_definitions()

        # Setup progress display (domain-specific)
        progress = RichLiveDisplay()

        def on_event(event: AgentEvent):
            # Update progress display
            progress.update(event)

        # Run agent (infrastructure handled by client)
        client = AgentClient(
            max_iterations=self.max_iterations,
            log_dir=self.agent_dir,
            verbose=True
        )

        result = client.run(
            llm_client=self.llm_client,
            model=self.model,
            initial_messages=initial_messages,
            tools=tools,
            execute_tool=self._execute_tool,  # Delegate to agent-specific logic
            is_complete=lambda msgs: hasattr(self, '_pending_analysis_content'),
            on_event=on_event,
            temperature=0.0
        )

        # Save domain-specific results
        if hasattr(self, '_pending_analysis_content'):
            self.analysis_path = self._save_analysis(
                result.messages,
                result.total_cost_usd,
                result.iterations
            )

        return {
            'analysis_path': self.analysis_path,
            'tool_calls_path': result.tool_calls_path,
            'cost_usd': result.total_cost_usd,
            'iterations': result.iterations,
            'model': self.model
        }

    def _execute_tool(self, tool_name: str, arguments: Dict) -> str:
        """Execute tool (domain-specific logic)."""
        if tool_name == "read_report":
            return self._read_report()
        elif tool_name == "load_page_data":
            return self._load_page_data(arguments["page_num"])
        # ... other tools
```

**Code Reduction**: ~150 lines eliminated (agent loop, logging, cost tracking now in AgentClient)

**Remaining Code**: ~50 lines of domain-specific logic (prompts, tools, result storage)

---

## Implementation Benefits

### 1. Code Deduplication
- **StageAnalyzer**: Eliminates ~150 lines of infrastructure code
- **TocFinderAgent**: Eliminates ~120 lines of infrastructure code
- **Future Agents**: Only need to implement domain logic (~50 lines vs ~200 lines)

### 2. Consistency
- All agents use identical tool call logging format (JSONL)
- Consistent cost tracking and iteration limits
- Standardized event system for progress tracking

### 3. Testing
- Test AgentClient infrastructure once, thoroughly
- Individual agents only test domain logic (tools, prompts)
- Easier to add integration tests for agent behavior

### 4. Observability
- Centralized tool call logging
- Consistent event structure for monitoring
- Easy to add metrics/tracing in one place

### 5. Maintenance
- Bug fixes in agent loop benefit all agents
- Easy to add features (e.g., retry logic, timeout handling)
- Clear separation of concerns

---

## Migration Steps

### Phase 1: Create AgentClient (1-2 hours)
1. Create `infra/llm/agent_client.py`
2. Implement core loop, logging, event system
3. Add comprehensive docstrings
4. Write unit tests for core functionality

### Phase 2: Refactor StageAnalyzer (30 min)
1. Update `infra/agents/stage_analyzer.py` to use AgentClient
2. Remove duplicated infrastructure code
3. Keep domain-specific logic (prompts, tools, Rich display)
4. Test with existing analysis runs

### Phase 3: Refactor TocFinderAgent (30 min)
1. Update `infra/agents/toc_finder.py` to use AgentClient
2. Remove duplicated infrastructure code
3. Keep domain-specific logic (ToC tools, prompts)
4. Test with build-structure stage

### Phase 4: Documentation (15 min)
1. Add AgentClient usage guide to `docs/architecture/`
2. Update stage implementation guide to reference AgentClient
3. Add examples for creating new agents

**Total Estimated Time**: 3-4 hours

---

## Open Questions / Design Decisions

### 1. Progress Display Integration
**Option A**: AgentClient provides default progress display (simple prints)
**Option B**: Agents provide custom progress via event callbacks (current proposal)

**Recommendation**: Option B - Keeps client simple, allows flexible displays

### 2. Tool Execution Interface
**Option A**: AgentClient calls agent methods directly (tight coupling)
**Option B**: Agent provides `execute_tool(name, args)` function (current proposal)

**Recommendation**: Option B - Clean interface, easy testing

### 3. Termination Logic
**Option A**: AgentClient checks for special tool name ("write_result")
**Option B**: Agent provides `is_complete(messages)` function (current proposal)

**Recommendation**: Option B - More flexible, supports different completion criteria

### 4. Event Granularity
**Current Proposal**: Events for iteration start/end, LLM call, tool execution

**Alternative**: Add events for tool call parsing, message building, error recovery

**Recommendation**: Start minimal (current proposal), add events as needed

---

## Future Extensions (Not in Scope)

These could be added later based on usage patterns:

1. **Retry Logic**: Retry failed LLM calls (like batch client)
2. **Streaming Support**: Stream LLM responses with TTFT tracking
3. **Parallel Tool Execution**: Execute independent tools in parallel
4. **Checkpointing**: Save/resume agent state mid-execution
5. **Rate Limiting**: Throttle LLM calls for cost control

---

## Conclusion

Creating `AgentClient` provides significant value:

- **Immediate**: Eliminates ~270 lines of duplicated code across two agents
- **Ongoing**: Makes future agents 3-4x faster to implement
- **Quality**: Centralized testing and error handling
- **Consistency**: Standardized logging and telemetry

The design follows proven patterns from `LLMBatchClient` while adapting to the sequential nature of agent workflows. The event-driven architecture provides flexibility for different progress displays while keeping the core infrastructure simple and testable.

**Recommendation**: Proceed with implementation using the proposed API design.
