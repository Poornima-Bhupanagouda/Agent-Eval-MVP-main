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
            "What is the {topic} amount or limit?",
            "How much is the {topic}?",
        ],
        "duration": [
            "How many days of {topic} are provided?",
            "What is the duration for {topic}?",
        ],
        "definition": [
            "What is {topic}?",
            "Explain {topic}.",
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
            "What are the steps for {topic}?",
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

        # Skip section titles that are too generic (like "Document")
        if section_title.lower() in ("document", "untitled", ""):
            section_title = "general"

        # Pattern 1: Numeric facts ("X days", "$X per year", "X%", "INR X")
        numeric_pattern = re.compile(
            r'([^.!?\n]+?(?:\$[\d,]+(?:\.\d+)?|INR\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?%?)\s*(?:days?|weeks?|months?|years?|hours?|sessions?|per\s+\w+|of\s+\w+|salary|per\s+annum)[^.!?\n]*)',
            re.IGNORECASE
        )
        for match in numeric_pattern.finditer(text):
            sentence = match.group(0).strip()
            if len(sentence) > 15:
                # Determine sub-type: duration vs monetary
                sub_type = "numeric"
                if any(w in sentence.lower() for w in ['day', 'week', 'month', 'year', 'duration']):
                    sub_type = "duration"
                facts.append({
                    "type": sub_type,
                    "claim": sentence,
                    "section": section_title,
                    "full_sentence": sentence,
                })

        # Pattern 2: Bullet points with key information ("Key: value" format)
        bullet_pattern = re.compile(r'^\s*[-•*]\s+\*?\*?(.+?)(?:\*?\*?)$', re.MULTILINE)
        for match in bullet_pattern.finditer(text):
            bullet_text = match.group(1).strip().rstrip(':')
            # Clean markdown bold markers
            bullet_text = re.sub(r'\*\*(.+?)\*\*', r'\1', bullet_text)
            bullet_text = bullet_text.strip('*').strip()
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
            # Clean markdown
            first_sentence = re.sub(r'\*\*(.+?)\*\*', r'\1', first_sentence)
            first_sentence = first_sentence.strip('*').strip()
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

        # Skip overly generic sections — try to extract a topic from the claim instead
        generic_names = ("document", "untitled", "general", "")
        source_stem = Path(source_file).stem.replace('_', ' ').replace('-', ' ').title()
        # Detect filename-based sections (e.g., "Employee Benefits Guide D4")
        is_generic = section.lower() in generic_names or section.lower() == source_stem.lower()

        if is_generic:
            # Extract a meaningful topic from the claim itself
            topic_from_claim = self._extract_topic(claim, section)
            if topic_from_claim and len(topic_from_claim) > 3:
                section = topic_from_claim.title()
            else:
                section = source_stem

        # Generate question based on fact type
        if fact_type == "qa":
            question = self._clean_markdown(fact.get("question", f"What about {section.lower()}?"))
            expected = claim
            metrics = ["answer_relevancy", "faithfulness", "contextual_relevancy"]
        elif fact_type == "duration":
            # Extract the specific subject from the claim (e.g., "education leave", "PL", "casual leaves")
            subject = self._extract_subject_from_claim(claim)
            if any(w in claim.lower() for w in ['week', 'weeks']):
                question = f"How many weeks of {subject} are provided?"
            elif any(w in claim.lower() for w in ['day', 'days']):
                question = f"How many days of {subject} are provided?"
            elif any(w in claim.lower() for w in ['month', 'months']):
                question = f"What is the {subject} duration in months?"
            elif any(w in claim.lower() for w in ['year', 'years']):
                question = f"What is the yearly {subject} allowance?"
            else:
                question = f"What is the duration for {subject}?"
            expected = claim
            metrics = ["answer_relevancy", "faithfulness", "correctness"]
        elif fact_type == "numeric":
            subject = self._extract_subject_from_claim(claim)
            if '$' in claim or 'inr' in claim.lower():
                question = f"What is the cost or amount for {subject}?"
            elif '%' in claim:
                question = f"What is the percentage for {subject}?"
            else:
                question = f"What is the {subject} amount or limit?"
            expected = claim
            metrics = ["answer_relevancy", "faithfulness", "correctness"]
        elif fact_type == "definition":
            # For "key: value" bullet points
            if ':' in claim:
                key, value = claim.split(':', 1)
                key_clean = self._clean_markdown(key.strip().lower())
                value_clean = self._clean_markdown(value.strip())
                # Build question using both section context AND the key
                if section.lower() != key_clean:
                    question = f"What is the {key_clean} under {section.lower()}?"
                else:
                    question = f"What is {key_clean}?"
                expected = value_clean
            else:
                topic = self._extract_topic(claim, section)
                question = self._pick_question(fact_type, topic)
                expected = claim
            metrics = ["answer_relevancy", "faithfulness"]
        elif fact_type == "process":
            topic = section.lower().replace("process", "").strip()
            if not topic:
                topic = "this"
            question = f"What are the steps for {topic}?"
            expected = claim
            metrics = ["answer_relevancy", "faithfulness", "task_completion"]
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
            metrics=metrics,
            source_file=source_file,
            difficulty=self._estimate_difficulty(fact_type, claim),
        )

    def _clean_markdown(self, text: str) -> str:
        """Remove markdown formatting from text."""
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # Bold
        text = re.sub(r'\*(.+?)\*', r'\1', text)  # Italic
        text = re.sub(r'`(.+?)`', r'\1', text)  # Code
        text = re.sub(r'#{1,4}\s*', '', text)  # Headers
        text = text.strip('*').strip()
        # Remove leftover double-asterisks
        text = text.replace('**', '')
        return text

    def _extract_topic(self, claim: str, section: str) -> str:
        """Extract the topic/subject from a factual claim."""
        clean = self._clean_markdown(claim).lower().strip()

        # Try to find a meaningful noun phrase after common verbs
        # e.g. "You get 5 days of education leave" → "education leave"
        after_verb = re.search(
            r'\b(?:of|for|to|towards|on|under|during|regarding)\s+(.{5,40}?)(?:\s*(?:per|in|at|from|that|which|,|\.|\(|$))',
            clean
        )
        if after_verb:
            topic = after_verb.group(1).strip().strip('.,;:')
            # Remove leading articles
            topic = re.sub(r'^(?:the|a|an)\s+', '', topic).strip()
            if len(topic) >= 4 and topic not in ('your', 'their', 'this', 'that', 'salary'):
                return topic

        # Try to extract topic from "X leave", "X insurance", "X benefit" patterns
        domain_match = re.search(
            r'(\w[\w\s]{2,25}?)\s+(?:leave|insurance|benefit|plan|allowance|coverage|policy|reimbursement|stipend|program|days?|weeks?)',
            clean
        )
        if domain_match:
            topic = domain_match.group(1).strip()
            topic = re.sub(r'^(?:the|a|an|your|our|all|each)\s+', '', topic).strip()
            if len(topic) >= 3:
                return topic

        # Fallback: use section title if it's not generic
        if section.lower() not in ("document", "untitled", "general", ""):
            return section.lower()

        # Last resort: take first meaningful words from claim
        words = re.sub(r'^(?:the|a|an|you|we|they|all|each|every|at\s+\w+,?)\s+', '', clean).split()[:4]
        topic = ' '.join(words).strip('.,;:')
        return topic if len(topic) >= 3 else section.lower()

    def _pick_question(self, fact_type: str, topic: str) -> str:
        """Pick a question template for the fact type."""
        import random
        templates = self.QUESTION_TEMPLATES.get(fact_type, self.QUESTION_TEMPLATES["definition"])
        template = random.choice(templates)
        return template.format(topic=topic)

    def _extract_subject_from_claim(self, claim: str) -> str:
        """Extract the main subject/object being described in a factual claim.

        Examples:
            'You also get 5 days of education leave' → 'education leave'
            'At Lilly, you are entitled to a total of 25 days of PL per annum' → 'privilege leave (PL)'
            '• 26 weeks for the first two children' → 'maternity leave for first two children'
            'Dental costs $25/month' → 'dental coverage'
            'At Lilly, 12% of the basic salary is deducted' → 'salary deduction (PF)'
        """
        clean = self._clean_markdown(claim).lower().strip()
        clean = clean.lstrip('•-* ').strip()

        # Pattern 1: "X days/weeks of SUBJECT" — extract SUBJECT
        of_match = re.search(r'\d+\s*(?:days?|weeks?|months?)\s+(?:of|for)\s+(.{3,40}?)(?:\s*(?:per|in|at|from|,|\.|and|which|that|$))', clean)
        if of_match:
            subject = of_match.group(1).strip().strip('.,;:')
            return re.sub(r'^(?:the|a|an)\s+', '', subject).strip()

        # Pattern 2: "SUBJECT: value" or "SUBJECT - value"
        colon_match = re.match(r'^([^:]{3,40}):', clean)
        if colon_match:
            subject = colon_match.group(1).strip()
            return re.sub(r'^(?:the|a|an)\s+', '', subject).strip()

        # Pattern 3: look for domain keywords (leave, insurance, benefit, plan, etc.)
        domain_match = re.search(
            r'((?:\w+\s+){0,3}(?:leave|insurance|benefit|plan|allowance|coverage|reimbursement|stipend|program|contribution|salary|deduction))',
            clean
        )
        if domain_match:
            subject = domain_match.group(1).strip()
            return re.sub(r'^(?:the|a|an|your|our)\s+', '', subject).strip()

        # Fallback: use _extract_topic
        return self._extract_topic(claim, "")

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
        clean_section = self._clean_markdown(re.sub(r'[^\w\s\-()]', '', section).strip())
        claim_clean = self._clean_markdown(claim)
        claim_words = claim_clean.split()[:6]
        claim_snippet = ' '.join(claim_words)
        type_label = {"qa": "Q&A", "numeric": "Fact", "duration": "Duration", "definition": "Info", "process": "Steps"}.get(fact_type, fact_type)
        return f"{clean_section} - {type_label} - {claim_snippet}"

    def _estimate_difficulty(self, fact_type: str, claim: str) -> str:
        """Estimate test difficulty."""
        if fact_type == "qa":
            return "easy"
        elif fact_type in ("numeric", "duration") and ('$' in claim or 'inr' in claim.lower()):
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
