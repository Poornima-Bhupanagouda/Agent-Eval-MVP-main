"""
Synthetic test generator for Lilly Agent Eval.

Generates test cases from knowledge base documents by extracting
facts and building question/answer/context triples.
"""

import re
import logging
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field

from agent_eval.core.file_parser import FileParser

logger = logging.getLogger(__name__)


@dataclass
class GeneratedTest:
    """A synthetically generated test case."""
    name: str
    input: str  # The question
    expected: str  # Expected answer (extracted fact)
    context: List[str]  # Source context chunks
    metrics: List[str]  # Recommended metrics
    source_file: str  # Which KB file it came from
    difficulty: str = "medium"  # easy, medium, hard


class TestGenerator:
    """
    Generate test cases from knowledge base documents.

    Approach: Parse documents into sections, extract factual claims,
    and generate question/answer pairs with context. No LLM required —
    uses heuristic extraction for deterministic, fast generation.
    """

    # Question templates by fact type
    QUESTION_TEMPLATES = {
        "numeric": [
            "How many {topic}?",
            "What is the number of {topic}?",
            "How much {topic}?",
        ],
        "definition": [
            "What is {topic}?",
            "Explain {topic}.",
            "Describe {topic}.",
        ],
        "policy": [
            "What is the policy on {topic}?",
            "What are the rules for {topic}?",
        ],
        "eligibility": [
            "Who is eligible for {topic}?",
            "What are the requirements for {topic}?",
        ],
        "process": [
            "How do I {topic}?",
            "What is the process for {topic}?",
        ],
    }

    def __init__(self, kb_dir: Optional[str] = None):
        self.kb_dir = kb_dir

    def generate_from_directory(
        self,
        directory: str,
        max_tests_per_file: int = 10,
    ) -> List[GeneratedTest]:
        """Generate tests from all supported files in a directory."""
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        all_tests = []
        for file_path in sorted(dir_path.iterdir()):
            if file_path.suffix.lower() in FileParser.SUPPORTED_EXTENSIONS:
                try:
                    tests = self.generate_from_file(
                        str(file_path),
                        max_tests=max_tests_per_file,
                    )
                    all_tests.extend(tests)
                    logger.info(f"Generated {len(tests)} tests from {file_path.name}")
                except Exception as e:
                    logger.warning(f"Skipping {file_path.name}: {e}")

        return all_tests

    def generate_from_file(
        self,
        file_path: str,
        max_tests: int = 10,
    ) -> List[GeneratedTest]:
        """Generate tests from a single knowledge base file."""
        path = Path(file_path)
        content = path.read_bytes()
        text = FileParser.parse(content, path.name)

        if not text.strip():
            return []

        # Split into sections
        sections = self._split_into_sections(text)

        # Extract facts from each section
        tests = []
        for section_title, section_text in sections:
            facts = self._extract_facts(section_text, section_title)
            for fact in facts:
                test = self._fact_to_test(fact, section_text, path.name)
                if test:
                    tests.append(test)

        # Deduplicate and limit
        tests = self._deduplicate(tests)
        return tests[:max_tests]

    def generate_from_text(
        self,
        text: str,
        source_name: str = "uploaded_text",
        max_tests: int = 10,
    ) -> List[GeneratedTest]:
        """Generate tests from raw text content."""
        if not text.strip():
            return []

        sections = self._split_into_sections(text)
        tests = []

        for section_title, section_text in sections:
            facts = self._extract_facts(section_text, section_title)
            for fact in facts:
                test = self._fact_to_test(fact, section_text, source_name)
                if test:
                    tests.append(test)

        tests = self._deduplicate(tests)
        return tests[:max_tests]

    def _split_into_sections(self, text: str) -> List[Tuple[str, str]]:
        """Split document into titled sections."""
        sections = []
        # Match markdown headers
        header_pattern = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)
        matches = list(header_pattern.finditer(text))

        if not matches:
            # No headers — treat whole text as one section
            return [("Document", text)]

        for i, match in enumerate(matches):
            title = match.group(2).strip().strip('*')
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            if section_text:
                sections.append((title, section_text))

        return sections

    def _extract_facts(self, text: str, section_title: str) -> List[Dict]:
        """Extract factual claims from a section."""
        facts = []

        # Pattern 1: Numeric facts ("X days", "$X per year", "X%")
        numeric_pattern = re.compile(
            r'([^.!?\n]+?(?:\$[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?%?)\s*(?:days?|weeks?|months?|years?|hours?|sessions?|per\s+\w+|of\s+\w+|salary)[^.!?\n]*)',
            re.IGNORECASE
        )
        for match in numeric_pattern.finditer(text):
            sentence = match.group(0).strip()
            if len(sentence) > 15:
                facts.append({
                    "type": "numeric",
                    "claim": sentence,
                    "section": section_title,
                })

        # Pattern 2: Bullet points with key information
        bullet_pattern = re.compile(r'^\s*[-•*]\s+\*?\*?(.+?)(?:\*?\*?)$', re.MULTILINE)
        for match in bullet_pattern.finditer(text):
            bullet_text = match.group(1).strip().rstrip(':')
            if len(bullet_text) > 20 and ':' in bullet_text:
                facts.append({
                    "type": "definition",
                    "claim": bullet_text,
                    "section": section_title,
                })

        # Pattern 3: Q&A pairs
        qa_pattern = re.compile(
            r'\*?\*?Q:\s*(.+?)\*?\*?\s*\n\s*A:\s*(.+?)(?=\n\n|\*?\*?Q:|\Z)',
            re.DOTALL | re.IGNORECASE
        )
        for match in qa_pattern.finditer(text):
            question = match.group(1).strip().strip('*')
            answer = match.group(2).strip()
            # Take first sentence of answer
            first_sentence = re.split(r'[.!?]\s', answer)[0]
            facts.append({
                "type": "qa",
                "question": question,
                "claim": first_sentence,
                "section": section_title,
            })

        # Pattern 4: Process/step patterns
        process_pattern = re.compile(
            r'^\s*\d+\.\s+(.+)$', re.MULTILINE
        )
        process_steps = process_pattern.findall(text)
        if len(process_steps) >= 2:
            combined = "; ".join(s.strip() for s in process_steps[:4])
            facts.append({
                "type": "process",
                "claim": combined,
                "section": section_title,
            })

        return facts

    def _fact_to_test(
        self, fact: Dict, section_text: str, source_file: str
    ) -> Optional[GeneratedTest]:
        """Convert an extracted fact into a test case."""
        fact_type = fact["type"]
        claim = self._clean_markdown(fact["claim"])
        section = self._clean_markdown(fact["section"])

        # Generate question based on fact type
        if fact_type == "qa":
            question = self._clean_markdown(fact.get("question", f"What about {section.lower()}?"))
            expected = claim
        elif fact_type == "numeric":
            # Use section title as the topic for numeric questions
            topic = section.lower()
            question = f"What is the {topic} policy?"
            if any(w in claim.lower() for w in ['day', 'week', 'month', 'year']):
                question = f"How many {topic} days or duration?"
            elif '$' in claim or 'inr' in claim.lower():
                question = f"What is the cost or amount for {topic}?"
            expected = claim
        elif fact_type == "definition":
            # For "key: value" bullet points
            if ':' in claim:
                key, value = claim.split(':', 1)
                topic = self._clean_markdown(key.strip().lower())
                question = f"What is the {topic} policy?"
                expected = self._clean_markdown(value.strip())
            else:
                topic = self._extract_topic(claim, section)
                question = self._pick_question(fact_type, topic)
                expected = claim
        elif fact_type == "process":
            topic = section.lower().replace("process", "").strip()
            if not topic:
                topic = "this"
            question = f"What is the process for {topic}?"
            expected = claim
        else:
            return None

        if not question or not expected or len(expected) < 5:
            return None

        # Clean up any remaining markdown artifacts
        question = self._clean_markdown(question)
        expected = self._clean_markdown(expected)

        # Build context chunks from the section
        context_chunks = self._build_context_chunks(section_text)

        # Generate a readable test name
        name = self._generate_test_name(section, fact_type, claim)

        return GeneratedTest(
            name=name,
            input=question,
            expected=expected,
            context=context_chunks,
            metrics=["answer_relevancy", "faithfulness", "similarity"],
            source_file=source_file,
            difficulty=self._estimate_difficulty(fact_type, claim),
        )

    def _clean_markdown(self, text: str) -> str:
        """Remove markdown formatting from text."""
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # Bold
        text = re.sub(r'\*(.+?)\*', r'\1', text)  # Italic
        text = re.sub(r'`(.+?)`', r'\1', text)  # Code
        text = text.strip('*').strip()
        return text

    def _extract_topic(self, claim: str, section: str) -> str:
        """Extract the topic/subject from a factual claim."""
        # Use section title as topic fallback
        topic = section.lower()

        # Try to extract a more specific topic from the claim
        # Remove leading articles and conjunctions
        clean = re.sub(r'^(the|a|an|all|each|every)\s+', '', claim.lower())

        # Take the first noun phrase (up to the first verb)
        verb_pattern = re.compile(r'\b(is|are|was|were|will|can|may|must|shall|should|receive|accrue|get|earn|provide|offer|cost)\b')
        verb_match = verb_pattern.search(clean)
        if verb_match:
            topic = clean[:verb_match.start()].strip()

        # Clean up
        topic = topic.strip('- *:').strip()
        if len(topic) < 3:
            topic = section.lower()

        return topic

    def _pick_question(self, fact_type: str, topic: str) -> str:
        """Pick a question template for the fact type."""
        import random
        templates = self.QUESTION_TEMPLATES.get(fact_type, self.QUESTION_TEMPLATES["definition"])
        template = random.choice(templates)
        return template.format(topic=topic)

    def _build_context_chunks(self, section_text: str) -> List[str]:
        """Build context chunks from section text."""
        # Split into sentences/paragraphs
        chunks = []
        paragraphs = [p.strip() for p in section_text.split('\n\n') if p.strip()]

        for para in paragraphs:
            # Split long paragraphs into smaller chunks
            sentences = re.split(r'(?<=[.!?])\s+', para)
            current_chunk = []
            current_len = 0

            for sentence in sentences:
                if current_len + len(sentence) > 300 and current_chunk:
                    chunks.append(' '.join(current_chunk))
                    current_chunk = []
                    current_len = 0
                current_chunk.append(sentence)
                current_len += len(sentence)

            if current_chunk:
                chunks.append(' '.join(current_chunk))

        # Return top 3 most relevant chunks
        return chunks[:3]

    def _generate_test_name(self, section: str, fact_type: str, claim: str) -> str:
        """Generate a readable test name."""
        clean_section = self._clean_markdown(re.sub(r'[^\w\s]', '', section).strip())
        claim_clean = self._clean_markdown(claim)
        claim_words = claim_clean.split()[:5]
        claim_snippet = ' '.join(claim_words)
        return f"{clean_section} - {claim_snippet}"

    def _estimate_difficulty(self, fact_type: str, claim: str) -> str:
        """Estimate test difficulty."""
        if fact_type == "qa":
            return "easy"
        elif fact_type == "numeric" and '$' in claim:
            return "medium"
        elif fact_type == "process":
            return "hard"
        return "medium"

    def _deduplicate(self, tests: List[GeneratedTest]) -> List[GeneratedTest]:
        """Remove tests with very similar questions."""
        seen_questions = set()
        unique_tests = []

        for test in tests:
            # Normalize question for dedup
            normalized = re.sub(r'[^\w\s]', '', test.input.lower()).strip()
            if normalized not in seen_questions:
                seen_questions.add(normalized)
                unique_tests.append(test)

        return unique_tests

    def to_yaml_dict(self, tests: List[GeneratedTest], suite_name: str = "Generated Tests") -> Dict:
        """Convert generated tests to YAML-compatible dict."""
        return {
            "name": suite_name,
            "description": f"Auto-generated from knowledge base ({len(tests)} tests)",
            "threshold": 70,
            "tests": [
                {
                    "name": t.name,
                    "input": t.input,
                    "expected": t.expected,
                    "context": t.context,
                    "metrics": t.metrics,
                }
                for t in tests
            ],
        }
