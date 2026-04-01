# Lilly Agent Evaluation Framework - Knowledge Base

## Overview
The Lilly Agent Evaluation Framework is an open-source tool designed to evaluate AI agents' performance across multiple dimensions including accuracy, safety, and responsiveness.

## Key Features
- **Multi-metric evaluation**: Support for 12+ evaluation metrics
- **RAG context support**: Upload documents to test context-aware responses
- **Batch testing**: Run hundreds of tests simultaneously
- **Authentication**: Support for Bearer tokens, API keys, and Basic auth

## Supported File Formats
- PDF documents (.pdf)
- Markdown files (.md)
- Word documents (.docx)
- Excel spreadsheets (.xlsx, .xls)
- CSV files (.csv)
- Plain text (.txt)

## Technical Architecture
The framework uses FastAPI for the backend and a vanilla JavaScript frontend. Data is stored in SQLite for persistence.

## Evaluation Metrics
1. **Exact Match**: Checks if output exactly matches expected
2. **Contains**: Checks if output contains expected text
3. **Semantic Similarity**: Uses embeddings to measure meaning similarity
4. **Latency SLA**: Validates response time is within threshold
5. **Context Recall**: Measures how well context is used in response

## API Endpoints
- POST /api/test - Run a single evaluation
- POST /api/batch - Run batch evaluations
- GET /api/metrics - List available metrics
- POST /api/upload-context - Upload context files

## Version
Current version: 3.0.0
