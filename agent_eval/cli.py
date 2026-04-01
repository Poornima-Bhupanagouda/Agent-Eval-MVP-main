"""
CLI for Lilly Agent Eval.

Simple command-line interface for running evaluations.
"""

import argparse
import asyncio
import sys
import json
from pathlib import Path

from agent_eval.core.evaluator import Evaluator
from agent_eval.core.executor import Executor


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Lilly Agent Eval - Simple Agent Evaluation",
        prog="agent-eval"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start the web UI")
    start_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    start_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    start_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    # Test command
    test_parser = subparsers.add_parser("test", help="Run a quick test")
    test_parser.add_argument("endpoint", help="Agent endpoint URL")
    test_parser.add_argument("input", help="Input text to send")
    test_parser.add_argument("--expected", help="Expected output")
    test_parser.add_argument("--context", nargs="+", help="Context documents for RAG")
    test_parser.add_argument("--metrics", nargs="+", help="Metrics to run")
    test_parser.add_argument("--threshold", type=float, default=70.0, help="Pass threshold")
    test_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Run command (YAML tests)
    run_parser = subparsers.add_parser("run", help="Run YAML test files")
    run_parser.add_argument("patterns", nargs="+", help="YAML file patterns")
    run_parser.add_argument("--threshold", type=float, help="Global pass threshold")
    run_parser.add_argument("--fail-fast", action="store_true", help="Stop on first failure")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    run_parser.add_argument("--output", choices=["text", "json"], default="text", help="Output format")
    run_parser.add_argument("--output-file", help="Write results to file (JSON)")
    run_parser.add_argument("--concurrency", type=int, default=1, help="Parallel test execution (1-20)")

    args = parser.parse_args()

    if args.command == "start":
        start_server(args)
    elif args.command == "test":
        sys.exit(run_test(args))
    elif args.command == "run":
        sys.exit(run_yaml_tests(args))
    else:
        parser.print_help()
        sys.exit(0)


def start_server(args):
    """Start the web UI server."""
    import uvicorn
    from agent_eval.web.app import app

    print(f"\n  Lilly Agent Eval v3.0.0")
    print(f"  Starting server at http://{args.host}:{args.port}")
    print(f"  Press Ctrl+C to stop\n")

    uvicorn.run(
        "agent_eval.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def run_test(args) -> int:
    """Run a quick test from command line."""
    async def _run():
        executor = Executor()
        evaluator = Evaluator()

        # Execute
        print(f"Testing endpoint: {args.endpoint}")
        print(f"Input: {args.input[:50]}...")

        exec_result = await executor.execute(args.endpoint, args.input)

        if exec_result.error:
            print(f"\nError: {exec_result.error}")
            return 1

        print(f"Output: {exec_result.output[:100]}...")
        print(f"Latency: {exec_result.latency_ms}ms")

        # Evaluate
        eval_results = evaluator.evaluate(
            input_text=args.input,
            output=exec_result.output,
            expected=args.expected,
            context=args.context,
            metrics=args.metrics,
            threshold=args.threshold,
        )

        if args.json:
            print(json.dumps({
                "output": exec_result.output,
                "latency_ms": exec_result.latency_ms,
                "evaluations": [
                    {"metric": r.metric, "score": r.score, "passed": r.passed, "reason": r.reason}
                    for r in eval_results
                ]
            }, indent=2))
        else:
            print("\nEvaluations:")
            for r in eval_results:
                status = "PASS" if r.passed else "FAIL"
                print(f"  [{status}] {r.metric}: {r.score}% - {r.reason}")

        all_passed = all(r.passed for r in eval_results)
        return 0 if all_passed else 1

    return asyncio.run(_run())


def run_yaml_tests(args) -> int:
    """Run YAML test files."""
    import glob
    import yaml

    async def _run():
        executor = Executor()
        evaluator = Evaluator()

        # Find all YAML files
        yaml_files = []
        for pattern in args.patterns:
            yaml_files.extend(glob.glob(pattern))

        if not yaml_files:
            print(f"No YAML files found matching: {args.patterns}")
            return 1

        is_json = args.output == "json"
        if not is_json:
            print(f"Found {len(yaml_files)} test file(s)")

        total_tests = 0
        passed_tests = 0
        failed_tests = []
        all_results = []  # For JSON output

        for yaml_file in yaml_files:
            if not is_json:
                print(f"\n{'='*50}")
                print(f"Running: {yaml_file}")
                print('='*50)

            with open(yaml_file) as f:
                suite = yaml.safe_load(f)

            endpoint = suite.get("endpoint")
            suite_threshold = args.threshold or suite.get("threshold", 70)
            tests = suite.get("tests", [])

            async def run_single(i, test):
                test_name = test.get("name", f"Test {i+1}")
                test_input = test.get("input", "")
                test_expected = test.get("expected") or test.get("ground_truth")
                test_context = test.get("context")
                test_metrics = test.get("metrics")
                test_threshold = test.get("threshold", suite_threshold)

                if not is_json and args.verbose:
                    print(f"\n  [{i+1}/{len(tests)}] {test_name}")
                    print(f"       Input: {test_input[:40]}...")

                try:
                    exec_result = await executor.execute(endpoint, test_input)
                except Exception as e:
                    return {
                        "file": yaml_file,
                        "name": test_name,
                        "input": test_input,
                        "error": str(e),
                        "passed": False,
                        "score": 0,
                    }

                if exec_result.error:
                    return {
                        "file": yaml_file,
                        "name": test_name,
                        "input": test_input,
                        "error": exec_result.error,
                        "passed": False,
                        "score": 0,
                    }

                eval_results = evaluator.evaluate(
                    input_text=test_input,
                    output=exec_result.output,
                    expected=test_expected,
                    context=test_context,
                    metrics=test_metrics,
                    threshold=test_threshold,
                )

                all_passed = all(r.passed for r in eval_results)
                avg_score = sum(r.score for r in eval_results) / len(eval_results) if eval_results else 0

                return {
                    "file": yaml_file,
                    "name": test_name,
                    "input": test_input,
                    "output": exec_result.output,
                    "score": round(avg_score, 1),
                    "passed": all_passed,
                    "latency_ms": exec_result.latency_ms,
                    "evaluations": [
                        {"metric": r.metric, "score": r.score, "passed": r.passed, "reason": r.reason}
                        for r in eval_results
                    ],
                }

            # Run tests (parallel if concurrency > 1)
            concurrency = max(1, min(getattr(args, 'concurrency', 1), 20))
            if concurrency > 1 and len(tests) > 1:
                import asyncio
                sem = asyncio.Semaphore(concurrency)
                async def limited(i, t):
                    async with sem:
                        return await run_single(i, t)
                results = await asyncio.gather(*[limited(i, t) for i, t in enumerate(tests)])
                results = list(results)
            else:
                results = []
                for i, test in enumerate(tests):
                    results.append(await run_single(i, test))

            for result in results:
                total_tests += 1
                all_results.append(result)

                if result.get("error"):
                    if not is_json:
                        print(f"  [FAIL] {result['name']}: {result['error']}")
                    failed_tests.append((yaml_file, result['name'], result['error']))
                    if args.fail_fast:
                        break
                elif result["passed"]:
                    passed_tests += 1
                    if not is_json:
                        print(f"  [PASS] {result['name']} - Score: {result['score']}%")
                else:
                    failed_tests.append((yaml_file, result['name'], "Evaluation failed"))
                    if not is_json:
                        print(f"  [FAIL] {result['name']} - Score: {result['score']}%")
                        if args.verbose:
                            for ev in result.get("evaluations", []):
                                status = "OK" if ev["passed"] else "XX"
                                print(f"         [{status}] {ev['metric']}: {ev['score']:.1f}%")
                    if args.fail_fast:
                        break

        # Output
        summary = {
            "total": total_tests,
            "passed": passed_tests,
            "failed": len(failed_tests),
            "pass_rate": round(passed_tests / total_tests * 100, 1) if total_tests > 0 else 0,
            "all_passed": len(failed_tests) == 0,
        }

        if is_json:
            output = {"summary": summary, "results": all_results}
            print(json.dumps(output, indent=2))
        else:
            print(f"\n{'='*50}")
            print(f"SUMMARY")
            print('='*50)
            print(f"Total:  {total_tests}")
            print(f"Passed: {passed_tests}")
            print(f"Failed: {len(failed_tests)}")
            print(f"Pass Rate: {summary['pass_rate']}%")

            if failed_tests:
                print(f"\nFailed tests:")
                for file, test, error in failed_tests:
                    print(f"  - {file}: {test}")

        # Write to file if requested
        if args.output_file:
            output_data = {"summary": summary, "results": all_results}
            with open(args.output_file, 'w') as f:
                json.dump(output_data, f, indent=2)
            if not is_json:
                print(f"\nResults written to: {args.output_file}")

        return 0 if len(failed_tests) == 0 else 1

    return asyncio.run(_run())


if __name__ == "__main__":
    main()
