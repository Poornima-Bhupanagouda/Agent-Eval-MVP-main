# AI Agent Types: Comprehensive Research for Lilly Agent Eval

**Version**: 1.0
**Date**: February 2026
**Purpose**: Define evaluation requirements for all major AI agent architectures

---

## Executive Summary

This document provides a comprehensive taxonomy of AI agent types that Lilly Agent Eval must support. Each agent type has unique characteristics that require specific input fields, evaluation metrics, and testing approaches. This research directly informs the input schemas and evaluation options needed in the framework.

---

## Table of Contents

1. [Simple Chat Agents](#1-simple-chat-agents)
2. [Conversational Agents](#2-conversational-agents)
3. [RAG Agents](#3-rag-agents)
4. [Tool-Using Agents](#4-tool-using-agents)
5. [ReAct Agents](#5-react-agents)
6. [Multi-Agent Systems](#6-multi-agent-systems)
7. [Autonomous Agents](#7-autonomous-agents)
8. [Code Generation Agents](#8-code-generation-agents)
9. [Vision/Multimodal Agents](#9-visionmultimodal-agents)
10. [Summary: Input Field Requirements](#10-summary-input-field-requirements)
11. [Implementation Recommendations](#11-implementation-recommendations)

---

## 1. Simple Chat Agents

### Description

Simple chat agents handle single-turn question-answering without maintaining conversation history. They receive a prompt and produce a response in isolation. These are the most basic form of LLM-based agents, typically used for stateless interactions like FAQ responses, simple classification, or one-off queries.

**Architecture Pattern**: `Input -> LLM -> Output`

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | string | Yes | The user query/prompt |
| `expected_output` | string | No | Expected response (for accuracy testing) |
| `system_prompt` | string | No | System prompt used (for reproducibility) |
| `model_config` | object | No | Temperature, max_tokens, etc. |
| `acceptable_outputs` | string[] | No | Multiple valid response variations |
| `keywords_required` | string[] | No | Must-include terms |
| `keywords_forbidden` | string[] | No | Must-exclude terms |

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Semantic Similarity** | How close is response to expected output | Embedding cosine similarity |
| **Answer Relevancy** | Does response address the question | LLM-as-judge scoring |
| **Toxicity Score** | Harmful content detection | Classification model |
| **Response Length** | Word/token count compliance | Rule-based counting |
| **Latency** | Response time in ms | Timestamp measurement |
| **Format Compliance** | Matches expected structure | JSON schema validation |

### Challenges

1. **Ambiguous "Correctness"**: Multiple valid answers exist for most questions
2. **Semantic vs. Lexical Match**: "Yes" and "Correct, that's right" mean the same thing
3. **Context-Free Evaluation**: Without conversation history, evaluating appropriateness is limited
4. **Tone/Style Evaluation**: Hard to quantify "helpfulness" or "professionalism"

### Example Use Cases

- **Customer Support FAQ Bot**: "What are your business hours?"
- **Classification Agent**: "Is this email spam or legitimate?"
- **Sentiment Analyzer**: "What's the sentiment of this review?"
- **Translation Agent**: "Translate this sentence to Spanish"
- **Summarization Bot**: "Summarize this paragraph in one sentence"

### Recommended Evaluators

- `rule_validation_agent` - Format and content rules
- `quality_assessment_agent` - Overall quality grading
- `toxicity_detection_agent` - Safety checks
- `semantic_similarity_agent` - Expected output comparison

---

## 2. Conversational Agents

### Description

Conversational agents maintain context across multiple turns of dialogue. They remember previous exchanges within a session and can reference earlier parts of the conversation. This requires memory management, coherent personality maintenance, and the ability to handle context switches.

**Architecture Pattern**: `(History + Current Input) -> LLM -> Output`

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `conversation_history` | Message[] | Yes | Previous turns in the conversation |
| `current_input` | string | Yes | Current user message |
| `expected_output` | string | No | Expected response |
| `session_id` | string | Yes | Conversation session identifier |
| `turn_number` | int | Yes | Position in conversation (1, 2, 3...) |
| `system_prompt` | string | No | Agent personality/instructions |
| `memory_context` | object | No | Any persisted memory/state |
| `expected_memory_updates` | object | No | Expected changes to memory |

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Context Coherence** | Does response align with conversation history | LLM coherence scoring |
| **Memory Retention** | Recalls information from earlier turns | Fact extraction + verification |
| **Coreference Resolution** | Correctly interprets "it", "that", "she" | Pronoun resolution testing |
| **Topic Continuity** | Maintains or appropriately shifts topics | Topic modeling analysis |
| **Personality Consistency** | Maintains consistent tone/character | Style consistency scoring |
| **Turn Appropriateness** | Response fits the conversation flow | LLM-as-judge |
| **Memory Accuracy** | Correctly stores/retrieves user information | Fact verification |

### Challenges

1. **Test Case Complexity**: Must define entire conversation histories, not just single inputs
2. **State Management**: Evaluating what the agent "remembers" requires introspection
3. **Multi-Turn Dependencies**: Later turn errors may stem from earlier turn failures
4. **Personality Drift**: Agent may subtly change behavior across long conversations
5. **Context Window Limits**: Long conversations may exceed model limits

### Example Use Cases

- **Virtual Assistant**: "Remember, I prefer metric units. Now, what's the weather?"
- **Therapy Chatbot**: Multi-session support with user history
- **Sales Agent**: Building rapport and tracking customer preferences
- **Education Tutor**: Progressive learning with state tracking
- **Healthcare Agent**: Tracking symptoms across multiple interactions

### Recommended Evaluators

- `quality_assessment_agent` - Response quality
- `hallucination_check_agent` - Fact consistency across turns
- `semantic_similarity_agent` - Expected response matching
- **NEW NEEDED**: `conversation_coherence_agent` - Multi-turn consistency
- **NEW NEEDED**: `memory_validation_agent` - State management verification

---

## 3. RAG Agents

### Description

Retrieval-Augmented Generation (RAG) agents combine information retrieval with language generation. They first retrieve relevant documents from a knowledge base, then use those documents as context to generate grounded responses. This reduces hallucination by anchoring responses in source material.

**Architecture Pattern**: `Query -> Retriever -> [Documents] -> LLM(Query + Documents) -> Output`

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | string | Yes | User query |
| `expected_output` | string | No | Expected response |
| `retrieval_context` | Document[] | Yes | Documents retrieved by the agent |
| `expected_context` | Document[] | No | Documents that should have been retrieved |
| `ground_truth` | string | No | Known correct answer from source |
| `knowledge_base_id` | string | No | Identifier for the knowledge source |
| `retrieval_config` | object | No | top_k, similarity_threshold, etc. |
| `source_documents` | Document[] | No | Full corpus for recall calculation |

**Document Schema**:
```json
{
  "content": "string",
  "source": "string (filename, URL, etc.)",
  "metadata": {
    "page_number": "int",
    "chunk_id": "string",
    "relevance_score": "float"
  }
}
```

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Faithfulness** | Is answer grounded in retrieved context | Statement-by-statement verification |
| **Answer Relevancy** | Does answer address the question | Question-answer alignment |
| **Context Precision** | Are retrieved docs actually relevant | Precision@k calculation |
| **Context Recall** | Were all relevant docs retrieved | Coverage against ground truth |
| **Groundedness Score** | Percentage of claims supported by sources | Claim extraction + verification |
| **Citation Accuracy** | Are source citations correct | Source-claim matching |
| **Hallucination Rate** | Claims not supported by context | Unsupported claim detection |
| **Retrieval Latency** | Time to retrieve documents | Timestamp measurement |

### Challenges

1. **Ground Truth Availability**: Often no "correct" set of documents to compare against
2. **Partial Relevance**: Documents may be partially relevant, not binary
3. **Multi-Hop Reasoning**: Answer may require synthesizing multiple documents
4. **Citation Granularity**: Tracing claims to specific document passages is complex
5. **Dynamic Knowledge Bases**: Documents change, invalidating historical tests
6. **Chunking Sensitivity**: Evaluation depends on how documents are chunked

### Example Use Cases

- **Enterprise Knowledge Bot**: "What's our policy on remote work?"
- **Legal Research Assistant**: Retrieving relevant case law
- **Medical Information Agent**: Answering drug interaction queries from databases
- **Customer Support with Docs**: Answering based on product documentation
- **Research Assistant**: Summarizing findings from scientific papers

### Recommended Evaluators

- `faithfulness_agent` - Answer grounded in context
- `answer_relevancy_agent` - Response addresses question
- `context_precision_agent` - Retrieval quality
- `context_recall_agent` - Retrieval completeness
- `context_validation_agent` - Context usage validation
- `hallucination_check_agent` - Fabrication detection

---

## 4. Tool-Using Agents

### Description

Tool-using agents can invoke external functions, APIs, or tools to accomplish tasks. They decide which tool to use, format the correct parameters, execute the call, and interpret results. This includes function calling, API integration, database queries, and external service orchestration.

**Architecture Pattern**: `Input -> LLM -> Tool Selection -> Tool Execution -> Result Processing -> Output`

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | string | Yes | User request |
| `expected_output` | string | No | Expected final response |
| `available_tools` | ToolSchema[] | Yes | Tools the agent can call |
| `expected_tool_calls` | ToolCall[] | No | Expected sequence of tool invocations |
| `actual_tool_calls` | ToolCall[] | Yes | What the agent actually called |
| `tool_results` | ToolResult[] | Yes | Results returned by tools |
| `mock_tool_responses` | object | No | Mocked responses for testing |

**ToolSchema**:
```json
{
  "name": "string",
  "description": "string",
  "parameters": {
    "type": "object",
    "properties": {...},
    "required": [...]
  }
}
```

**ToolCall**:
```json
{
  "tool_name": "string",
  "arguments": {...},
  "timestamp": "ISO8601",
  "result": "any"
}
```

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Tool Selection Accuracy** | Did agent choose the right tool | Compare against expected |
| **Parameter Accuracy** | Were parameters correctly formatted | Schema validation |
| **Call Sequence Correctness** | Correct order of tool calls | Sequence comparison |
| **Error Handling** | Graceful handling of tool failures | Fault injection testing |
| **Tool Efficiency** | Minimal unnecessary calls | Call count analysis |
| **Result Interpretation** | Correctly used tool output | Output-response coherence |
| **Schema Compliance** | Arguments match tool schema | JSON schema validation |

### Challenges

1. **Mocking Dependencies**: Tools may have side effects (sending emails, making purchases)
2. **Non-Deterministic Selection**: Multiple valid tools may accomplish the same task
3. **Argument Equivalence**: `{"date": "2024-01-15"}` vs `{"date": "January 15, 2024"}`
4. **Chain Evaluation**: Multi-step tool chains are hard to validate
5. **Real-Time Data**: Tool results change over time (stock prices, weather)
6. **Error Simulation**: Need to test agent behavior when tools fail

### Example Use Cases

- **Calendar Agent**: Scheduling meetings using Google Calendar API
- **Data Analysis Agent**: Running SQL queries on databases
- **E-commerce Agent**: Searching products, placing orders
- **Travel Agent**: Booking flights, hotels via external APIs
- **DevOps Agent**: Running shell commands, managing infrastructure

### Recommended Evaluators

- `tool_validation_agent` - Tool call correctness
- `quality_assessment_agent` - Final response quality
- **NEW NEEDED**: `tool_sequence_agent` - Multi-step tool chain validation
- **NEW NEEDED**: `tool_efficiency_agent` - Unnecessary call detection

---

## 5. ReAct Agents

### Description

ReAct (Reasoning + Acting) agents interleave reasoning traces with actions. They explicitly "think out loud" about what to do, take an action, observe the result, and continue reasoning. This creates interpretable chains of thought that can be evaluated for logical soundness.

**Architecture Pattern**:
```
Thought -> Action -> Observation -> Thought -> Action -> Observation -> ... -> Final Answer
```

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | string | Yes | User task/question |
| `expected_output` | string | No | Expected final answer |
| `reasoning_trace` | ReActStep[] | Yes | Full thought-action-observation chain |
| `expected_reasoning` | ReActStep[] | No | Expected reasoning path |
| `available_actions` | ActionSchema[] | Yes | Actions the agent can take |
| `max_steps` | int | No | Step limit for evaluation |
| `intermediate_checkpoints` | Checkpoint[] | No | Expected states at certain steps |

**ReActStep**:
```json
{
  "step_number": "int",
  "thought": "string",
  "action": "string",
  "action_input": "any",
  "observation": "string"
}
```

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Reasoning Validity** | Are thoughts logically sound | LLM-as-judge on reasoning |
| **Action Appropriateness** | Does action follow from thought | Thought-action coherence |
| **Observation Usage** | Reasoning incorporates observations | Reference checking |
| **Path Efficiency** | Reaches answer in minimal steps | Step count comparison |
| **Error Recovery** | Adjusts reasoning after failures | Recovery pattern detection |
| **Final Answer Correctness** | Correct conclusion reached | Answer comparison |
| **Reasoning Completeness** | No logical gaps in chain | Chain continuity analysis |

### Challenges

1. **Multiple Valid Paths**: Many reasoning chains lead to correct answer
2. **Thought Evaluation**: Assessing "quality" of reasoning is subjective
3. **Partial Credit**: Agent may reason well but fail at final step
4. **Verbose Reasoning**: Some agents over-explain, others under-explain
5. **Hindsight Bias**: Easy to see "correct" path after seeing answer
6. **Creativity vs. Correctness**: Novel approaches may be valid but unexpected

### Example Use Cases

- **Research Agent**: "Find out when the Eiffel Tower was built and who designed it"
- **Troubleshooting Agent**: Step-by-step diagnosis of technical issues
- **Math Problem Solver**: Showing work for complex calculations
- **Investigation Agent**: Gathering evidence to answer complex questions
- **Planning Agent**: Multi-step task decomposition

### Recommended Evaluators

- `quality_assessment_agent` - Overall reasoning quality
- `hallucination_check_agent` - Factual accuracy in reasoning
- **NEW NEEDED**: `reasoning_validity_agent` - Logical coherence checking
- **NEW NEEDED**: `path_efficiency_agent` - Optimal step count analysis

---

## 6. Multi-Agent Systems

### Description

Multi-agent systems involve multiple specialized agents working together, often orchestrated by a supervisor or through peer-to-peer communication. Agents may have different roles (researcher, writer, critic), share information, and collaborate to complete complex tasks.

**Architecture Pattern**:
```
Supervisor -> [Agent A, Agent B, Agent C] -> Aggregation -> Output
```
or
```
Agent A <-> Agent B <-> Agent C (peer collaboration)
```

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | string | Yes | Task/query for the system |
| `expected_output` | string | No | Expected final output |
| `agent_configs` | AgentConfig[] | Yes | Configuration for each agent |
| `communication_log` | Message[] | Yes | Inter-agent messages |
| `expected_delegation` | Delegation[] | No | Expected task assignments |
| `agent_outputs` | AgentOutput[] | Yes | Each agent's individual output |
| `orchestration_trace` | Event[] | Yes | Full orchestration history |

**AgentConfig**:
```json
{
  "agent_id": "string",
  "role": "string",
  "capabilities": ["string"],
  "model": "string"
}
```

**Message**:
```json
{
  "from_agent": "string",
  "to_agent": "string",
  "content": "string",
  "timestamp": "ISO8601",
  "message_type": "task|result|query|response"
}
```

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Delegation Accuracy** | Tasks assigned to appropriate agents | Role-task matching |
| **Collaboration Efficiency** | Minimal redundant communication | Message count analysis |
| **Agent Contribution** | Each agent adds value | Contribution scoring |
| **Conflict Resolution** | Disagreements handled well | Conflict detection + resolution |
| **Final Output Quality** | Combined output is good | Standard quality metrics |
| **Error Propagation** | Errors don't cascade through system | Fault tolerance testing |
| **Resource Utilization** | Agents used efficiently | Utilization metrics |

### Challenges

1. **Attribution**: Which agent caused a failure?
2. **Communication Overhead**: Evaluating if messaging is necessary or excessive
3. **Emergent Behavior**: System behavior may not be predictable from individual agents
4. **Coordination Failures**: Agents may work at cross purposes
5. **Debugging Complexity**: Tracing issues through multiple agents is difficult
6. **Configuration Explosion**: Many possible agent combinations to test

### Example Use Cases

- **Content Creation Pipeline**: Researcher -> Writer -> Editor -> Publisher
- **Software Development Team**: Architect -> Developer -> Tester
- **Customer Service Escalation**: Bot -> Specialist -> Supervisor
- **Data Processing Pipeline**: Collector -> Cleaner -> Analyzer -> Reporter
- **Debate System**: Proposer -> Opponent -> Judge

### Recommended Evaluators

- `quality_assessment_agent` - Final output quality
- `tool_validation_agent` - Inter-agent communication validation
- **NEW NEEDED**: `orchestration_validation_agent` - Delegation correctness
- **NEW NEEDED**: `agent_contribution_agent` - Individual agent value
- **NEW NEEDED**: `collaboration_efficiency_agent` - Communication analysis

---

## 7. Autonomous Agents

### Description

Autonomous agents operate with minimal human supervision, executing long-running tasks that may span hours or days. They manage their own planning, handle failures, persist state, and make independent decisions. Examples include AutoGPT-style agents that can browse the web, write files, and execute code.

**Architecture Pattern**:
```
Goal -> Planning -> [Execute -> Observe -> Replan]* -> Completion
```

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `goal` | string | Yes | High-level objective |
| `expected_outcome` | Outcome | No | Expected final state |
| `execution_log` | Event[] | Yes | Full execution history |
| `environment_snapshots` | Snapshot[] | Yes | State at checkpoints |
| `resources_consumed` | Resource[] | Yes | API calls, tokens, time, etc. |
| `human_interventions` | Intervention[] | Yes | Any human inputs during execution |
| `success_criteria` | Criteria[] | Yes | How to determine success |
| `safety_constraints` | Constraint[] | Yes | Boundaries agent must respect |

**Event**:
```json
{
  "timestamp": "ISO8601",
  "event_type": "plan|action|observation|error|decision",
  "content": "any",
  "metadata": {}
}
```

**Snapshot**:
```json
{
  "timestamp": "ISO8601",
  "state": {},
  "files_modified": ["string"],
  "external_changes": []
}
```

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Goal Achievement** | Was the objective accomplished | Success criteria evaluation |
| **Planning Quality** | Were plans reasonable and effective | Plan review scoring |
| **Execution Efficiency** | Minimal wasted steps/resources | Resource analysis |
| **Error Recovery** | Handled failures gracefully | Failure response evaluation |
| **Safety Compliance** | Stayed within boundaries | Constraint violation detection |
| **Autonomy Level** | Minimal human intervention needed | Intervention counting |
| **Progress Rate** | Steady progress toward goal | Progress curve analysis |
| **Resource Efficiency** | Cost/token/time within budget | Budget tracking |

### Challenges

1. **Long Time Horizons**: Tests may take hours/days to complete
2. **Non-Deterministic Execution**: Same goal may have very different execution paths
3. **Real-World Side Effects**: Actions may have permanent consequences
4. **Goal Ambiguity**: "Success" may be subjective for open-ended goals
5. **Checkpoint Evaluation**: Need to assess partial progress, not just final state
6. **Safety Monitoring**: Must ensure agent doesn't take harmful actions
7. **Resource Bounds**: Preventing runaway resource consumption

### Example Use Cases

- **Research Agent**: "Find and summarize all papers on topic X from the last year"
- **Web Agent**: "Book the cheapest flight to NYC next Tuesday"
- **Development Agent**: "Fix all failing tests in this repository"
- **Data Collection Agent**: "Gather competitive intelligence on company X"
- **Personal Assistant**: "Plan my vacation to Japan with budget Y"

### Recommended Evaluators

- `quality_assessment_agent` - Output quality
- `latency_sla_agent` - Time constraints
- `cost_budget_agent` - Resource limits
- **NEW NEEDED**: `goal_achievement_agent` - Success criteria evaluation
- **NEW NEEDED**: `safety_compliance_agent` - Constraint violation detection
- **NEW NEEDED**: `planning_quality_agent` - Plan effectiveness scoring

---

## 8. Code Generation Agents

### Description

Code generation agents write, modify, and execute code. They understand programming languages, can reason about code structure, generate syntactically correct code, and often execute code to verify correctness. This includes coding assistants, automated debugging tools, and code translation systems.

**Architecture Pattern**:
```
Requirement -> Code Generation -> [Execution -> Error Analysis -> Refinement]* -> Working Code
```

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_description` | string | Yes | What the code should do |
| `expected_code` | string | No | Reference implementation |
| `generated_code` | string | Yes | Agent's output code |
| `programming_language` | string | Yes | Target language |
| `test_cases` | TestCase[] | Yes | Input/output test cases |
| `execution_environment` | EnvConfig | No | Runtime environment specs |
| `existing_code_context` | string | No | Code to modify/extend |
| `style_guide` | StyleConfig | No | Coding standards to follow |

**TestCase**:
```json
{
  "input": "any",
  "expected_output": "any",
  "timeout_ms": "int",
  "description": "string"
}
```

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Functional Correctness** | Passes all test cases | Test execution |
| **Syntax Validity** | Code compiles/parses | Language parser |
| **Test Pass Rate** | Percentage of tests passed | Execution results |
| **Code Quality** | Readable, maintainable | Linting + complexity metrics |
| **Security** | No vulnerabilities | Static analysis |
| **Performance** | Meets efficiency requirements | Benchmarking |
| **Style Compliance** | Follows coding standards | Style checker |
| **Edit Distance** | Similarity to expected code | Diff analysis |

### Challenges

1. **Multiple Valid Solutions**: Many correct implementations exist
2. **Execution Safety**: Running generated code has security risks
3. **Environment Dependencies**: Code may work in one environment, not another
4. **Partial Solutions**: Code may solve 80% of the problem correctly
5. **Edge Cases**: Code may pass basic tests but fail edge cases
6. **Non-Functional Requirements**: Hard to test performance, maintainability
7. **Language Coverage**: Supporting many programming languages is complex

### Example Use Cases

- **Coding Assistant**: "Write a function to reverse a linked list"
- **Bug Fixer**: "Fix the bug in this code snippet"
- **Code Translator**: "Convert this Python code to JavaScript"
- **Test Generator**: "Write unit tests for this function"
- **Code Review Agent**: "Review this PR and suggest improvements"

### Recommended Evaluators

- `rule_validation_agent` - Syntax and format checks
- `quality_assessment_agent` - Code quality grading
- **NEW NEEDED**: `code_execution_agent` - Functional correctness testing
- **NEW NEEDED**: `code_security_agent` - Vulnerability detection
- **NEW NEEDED**: `code_style_agent` - Style compliance checking

---

## 9. Vision/Multimodal Agents

### Description

Vision and multimodal agents process multiple input types, typically combining images with text. They can describe images, answer questions about visual content, generate images from text, or perform tasks that require understanding both modalities together.

**Architecture Pattern**:
```
[Image + Text] -> Multimodal Encoder -> LLM -> Output (text/image/both)
```

### Required Inputs for Evaluation

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text_input` | string | No | Text query/prompt |
| `image_input` | ImageData | No | Image(s) to process |
| `audio_input` | AudioData | No | Audio content |
| `video_input` | VideoData | No | Video content |
| `expected_output` | MultimodalOutput | No | Expected response |
| `output_modality` | string | Yes | Expected output type (text/image/etc.) |
| `visual_annotations` | Annotation[] | No | Ground truth labels |

**ImageData**:
```json
{
  "data": "base64 or URL",
  "format": "png|jpg|etc.",
  "width": "int",
  "height": "int",
  "metadata": {}
}
```

**Annotation**:
```json
{
  "type": "bounding_box|segmentation|label|caption",
  "content": "any",
  "confidence": "float"
}
```

### Key Metrics

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Caption Accuracy** | Generated caption matches image | Caption similarity metrics |
| **Object Detection Accuracy** | Correctly identifies objects | IoU, mAP scores |
| **VQA Accuracy** | Correctly answers visual questions | Answer matching |
| **Image-Text Alignment** | Generated image matches prompt | CLIP score |
| **Spatial Understanding** | Understands object relationships | Spatial reasoning tests |
| **OCR Accuracy** | Correctly reads text in images | Character error rate |
| **Hallucination Detection** | Doesn't describe non-existent objects | Object grounding |

### Challenges

1. **Ground Truth Complexity**: Multiple valid descriptions of an image
2. **Evaluation Subjectivity**: "Good" image generation is subjective
3. **Modality Mismatch**: Comparing text outputs to visual inputs is complex
4. **Data Volume**: Images/videos are large, slowing evaluation
5. **Annotation Cost**: Creating ground truth for images is expensive
6. **Context Sensitivity**: Same image in different contexts needs different descriptions
7. **Temporal Understanding**: Video understanding requires temporal reasoning

### Example Use Cases

- **Image Captioning**: "Describe this medical scan"
- **Visual QA**: "How many people are in this photo?"
- **Document Analysis**: "Extract the table from this PDF image"
- **Image Generation**: "Create an image of a sunset over mountains"
- **Medical Imaging**: "Identify anomalies in this X-ray"
- **Chart Understanding**: "What trend does this graph show?"

### Recommended Evaluators

- `semantic_similarity_agent` - Text output similarity
- `quality_assessment_agent` - Overall quality
- `hallucination_check_agent` - Visual hallucination detection
- **NEW NEEDED**: `visual_grounding_agent` - Object mention verification
- **NEW NEEDED**: `image_quality_agent` - Generated image quality
- **NEW NEEDED**: `ocr_accuracy_agent` - Text extraction accuracy

---

## 10. Summary: Input Field Requirements

Based on the above research, here is the comprehensive set of input fields Lilly Agent Eval needs to support:

### Universal Fields (All Agent Types)

| Field | Type | Description |
|-------|------|-------------|
| `input` | string | Primary text input/query |
| `expected_output` | string | Expected response |
| `agent_type` | enum | Type of agent being tested |
| `evaluators` | string[] | List of evaluators to run |
| `metadata` | object | Additional context |

### Agent-Type-Specific Fields

#### Conversational Agents
- `conversation_history` - Previous turns
- `session_id` - Conversation identifier
- `turn_number` - Position in conversation
- `memory_context` - Persisted state

#### RAG Agents
- `retrieval_context` - Retrieved documents
- `expected_context` - Expected documents
- `ground_truth` - Known correct answer
- `knowledge_base_id` - Source identifier

#### Tool-Using Agents
- `available_tools` - Tool schemas
- `expected_tool_calls` - Expected invocations
- `actual_tool_calls` - Actual invocations
- `tool_results` - Execution results
- `mock_tool_responses` - Test fixtures

#### ReAct Agents
- `reasoning_trace` - Thought-action-observation chain
- `expected_reasoning` - Expected reasoning path
- `available_actions` - Action schemas
- `max_steps` - Step limit

#### Multi-Agent Systems
- `agent_configs` - Individual agent configs
- `communication_log` - Inter-agent messages
- `agent_outputs` - Individual outputs
- `orchestration_trace` - Full history

#### Autonomous Agents
- `goal` - High-level objective
- `execution_log` - Full execution history
- `environment_snapshots` - State checkpoints
- `success_criteria` - How to determine success
- `safety_constraints` - Boundaries

#### Code Generation Agents
- `task_description` - What code should do
- `generated_code` - Agent output
- `programming_language` - Target language
- `test_cases` - Input/output tests
- `existing_code_context` - Code to modify

#### Vision/Multimodal Agents
- `image_input` - Image data
- `audio_input` - Audio data
- `video_input` - Video data
- `output_modality` - Expected output type
- `visual_annotations` - Ground truth labels

---

## 11. Implementation Recommendations

### Priority 1: Immediate Implementation

These agent types are most common and should be fully supported first:

1. **Simple Chat Agents** - Already well supported
2. **RAG Agents** - Critical for enterprise, partially implemented
3. **Tool-Using Agents** - High demand, partially implemented
4. **Conversational Agents** - Common pattern, needs memory support

### Priority 2: Near-Term Implementation

5. **Code Generation Agents** - Growing demand, needs execution sandbox
6. **ReAct Agents** - Increasingly popular pattern
7. **Vision/Multimodal Agents** - Emerging capability

### Priority 3: Future Implementation

8. **Multi-Agent Systems** - Complex, emerging patterns
9. **Autonomous Agents** - Requires significant infrastructure

### Required New Evaluators

Based on this research, the following new evaluators should be developed:

| Evaluator | Priority | Agent Types |
|-----------|----------|-------------|
| `conversation_coherence_agent` | High | Conversational |
| `memory_validation_agent` | High | Conversational |
| `tool_sequence_agent` | High | Tool-Using |
| `reasoning_validity_agent` | Medium | ReAct |
| `code_execution_agent` | High | Code Generation |
| `code_security_agent` | Medium | Code Generation |
| `visual_grounding_agent` | Medium | Vision/Multimodal |
| `goal_achievement_agent` | Low | Autonomous |
| `orchestration_validation_agent` | Low | Multi-Agent |

### UI/UX Recommendations

1. **Dynamic Forms**: Show/hide fields based on selected agent type
2. **Smart Defaults**: Pre-populate common configurations
3. **Guided Wizards**: Step-by-step test case creation for complex types
4. **Schema Validation**: Validate inputs match agent type requirements
5. **Examples**: Provide sample test cases for each agent type

### Data Model Recommendations

1. **Flexible Schema**: Support arbitrary fields via JSON metadata
2. **Versioning**: Track schema versions as agent types evolve
3. **Inheritance**: Base test case with type-specific extensions
4. **Validation Rules**: Per-agent-type field validation

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Agent** | An AI system that can perceive, reason, and act |
| **RAG** | Retrieval-Augmented Generation |
| **ReAct** | Reasoning + Acting pattern |
| **Tool Calling** | Agent invoking external functions/APIs |
| **Multimodal** | Processing multiple input types (text, image, audio) |
| **Orchestration** | Coordinating multiple agents |
| **Faithfulness** | Response grounded in provided context |
| **Hallucination** | Generating false or unsupported information |
| **Context Window** | Maximum input length for LLM |

---

## Appendix B: References

1. **ReAct Paper**: "ReAct: Synergizing Reasoning and Acting in Language Models" (Yao et al., 2022)
2. **RAG Paper**: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (Lewis et al., 2020)
3. **RAGAS**: RAG Assessment framework
4. **LangChain**: Agent and tool framework
5. **AutoGPT**: Autonomous agent architecture
6. **GPT-4V**: Vision-language model capabilities
7. **Function Calling**: OpenAI function calling documentation

---

*Document created for Lilly Agent Eval framework development*
*Last updated: February 2026*
