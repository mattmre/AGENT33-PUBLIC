"""Default benchmark task catalog for the SkillsBench harness.

Provides a representative set of 20 benchmark tasks across 10 categories,
mirroring the SkillsBench 86-task evaluation structure.  Each task has
realistic descriptions, required skills, and verification configuration.

These are catalog definitions only -- the actual verification logic is
pluggable via the harness's trial executor.
"""

from __future__ import annotations

from agent33.evaluation.benchmark import BenchmarkTask, BenchmarkTaskCategory

# ---------------------------------------------------------------------------
# Scientific computing (3 tasks)
# ---------------------------------------------------------------------------

_SCI_01 = BenchmarkTask(
    task_id="SB-001",
    name="Matrix Eigenvalue Decomposition",
    category=BenchmarkTaskCategory.SCIENTIFIC_COMPUTING,
    description=(
        "Compute the eigenvalues and eigenvectors of a given symmetric matrix "
        "using numerical methods.  Verify the decomposition reconstructs the "
        "original matrix within a tolerance of 1e-10."
    ),
    difficulty="medium",
    required_skills=["numpy", "linear_algebra"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb001_eigenvalue.py",
        "tolerance": 1e-10,
    },
    timeout_seconds=120,
)

_SCI_02 = BenchmarkTask(
    task_id="SB-002",
    name="Numerical ODE Solver",
    category=BenchmarkTaskCategory.SCIENTIFIC_COMPUTING,
    description=(
        "Implement a fourth-order Runge-Kutta solver for a system of coupled "
        "ordinary differential equations.  Solve the Lorenz attractor system "
        "and verify trajectory bounds and energy conservation."
    ),
    difficulty="hard",
    required_skills=["numpy", "scipy", "differential_equations"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb002_ode_solver.py",
        "max_error": 1e-6,
    },
    timeout_seconds=180,
)

_SCI_03 = BenchmarkTask(
    task_id="SB-003",
    name="FFT Signal Processing",
    category=BenchmarkTaskCategory.SCIENTIFIC_COMPUTING,
    description=(
        "Apply Fast Fourier Transform to a noisy signal, identify dominant "
        "frequencies, and reconstruct a filtered signal.  Verify the "
        "reconstructed signal matches the original clean signal within SNR > 20dB."
    ),
    difficulty="medium",
    required_skills=["numpy", "signal_processing"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb003_fft.py",
        "min_snr_db": 20,
    },
    timeout_seconds=120,
)

# ---------------------------------------------------------------------------
# Security (2 tasks)
# ---------------------------------------------------------------------------

_SEC_01 = BenchmarkTask(
    task_id="SB-004",
    name="JWT Token Validation",
    category=BenchmarkTaskCategory.SECURITY,
    description=(
        "Implement a JWT token validator that checks signature, expiration, "
        "issuer, and audience claims.  Handle RS256 and HS256 algorithms.  "
        "Reject tokens with invalid or missing required claims."
    ),
    difficulty="medium",
    required_skills=["cryptography", "jwt", "security"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb004_jwt.py",
        "algorithms": ["RS256", "HS256"],
    },
    timeout_seconds=120,
)

_SEC_02 = BenchmarkTask(
    task_id="SB-005",
    name="SQL Injection Detection",
    category=BenchmarkTaskCategory.SECURITY,
    description=(
        "Build a SQL injection detector that identifies common injection "
        "patterns in user input.  Must detect UNION-based, boolean-based, "
        "and time-based blind injection attempts with fewer than 5% false positives."
    ),
    difficulty="hard",
    required_skills=["security", "sql", "pattern_matching"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb005_sqli.py",
        "max_false_positive_rate": 0.05,
    },
    timeout_seconds=180,
)

# ---------------------------------------------------------------------------
# Finance (2 tasks)
# ---------------------------------------------------------------------------

_FIN_01 = BenchmarkTask(
    task_id="SB-006",
    name="Black-Scholes Option Pricing",
    category=BenchmarkTaskCategory.FINANCE,
    description=(
        "Implement the Black-Scholes formula for European call and put options.  "
        "Compute option price, delta, gamma, vega, and theta Greeks.  "
        "Verify against known analytical solutions."
    ),
    difficulty="medium",
    required_skills=["finance", "numpy", "statistics"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb006_black_scholes.py",
        "tolerance": 1e-4,
    },
    timeout_seconds=120,
)

_FIN_02 = BenchmarkTask(
    task_id="SB-007",
    name="Portfolio Risk Assessment",
    category=BenchmarkTaskCategory.FINANCE,
    description=(
        "Calculate Value at Risk (VaR) and Conditional VaR for a portfolio "
        "of assets using historical simulation and Monte Carlo methods.  "
        "Report at 95% and 99% confidence levels."
    ),
    difficulty="hard",
    required_skills=["finance", "numpy", "statistics", "monte_carlo"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb007_portfolio_risk.py",
        "confidence_levels": [0.95, 0.99],
    },
    timeout_seconds=240,
)

# ---------------------------------------------------------------------------
# Media (2 tasks)
# ---------------------------------------------------------------------------

_MED_01 = BenchmarkTask(
    task_id="SB-008",
    name="Image Metadata Extraction",
    category=BenchmarkTaskCategory.MEDIA,
    description=(
        "Extract EXIF metadata from JPEG images including GPS coordinates, "
        "camera model, exposure settings, and creation date.  Handle images "
        "with missing or corrupted EXIF data gracefully."
    ),
    difficulty="easy",
    required_skills=["image_processing", "metadata"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb008_exif.py",
    },
    timeout_seconds=60,
)

_MED_02 = BenchmarkTask(
    task_id="SB-009",
    name="Audio Waveform Analysis",
    category=BenchmarkTaskCategory.MEDIA,
    description=(
        "Analyze audio files to compute RMS energy, zero-crossing rate, "
        "spectral centroid, and detect silence segments.  Output a JSON "
        "summary of the analysis results."
    ),
    difficulty="medium",
    required_skills=["audio_processing", "signal_processing", "numpy"],
    verification_type="output_match",
    verification_config={
        "expected_keys": [
            "rms_energy",
            "zero_crossing_rate",
            "spectral_centroid",
            "silence_segments",
        ],
    },
    timeout_seconds=120,
)

# ---------------------------------------------------------------------------
# Data analysis (2 tasks)
# ---------------------------------------------------------------------------

_DATA_01 = BenchmarkTask(
    task_id="SB-010",
    name="CSV Data Pipeline",
    category=BenchmarkTaskCategory.DATA_ANALYSIS,
    description=(
        "Build a data pipeline that reads a CSV file, handles missing values, "
        "normalizes numeric columns, encodes categorical features, and "
        "outputs a cleaned DataFrame.  Verify column types and null counts."
    ),
    difficulty="easy",
    required_skills=["pandas", "data_cleaning"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb010_csv_pipeline.py",
    },
    timeout_seconds=90,
)

_DATA_02 = BenchmarkTask(
    task_id="SB-011",
    name="Time Series Anomaly Detection",
    category=BenchmarkTaskCategory.DATA_ANALYSIS,
    description=(
        "Implement an anomaly detection algorithm for univariate time series "
        "data using z-score and IQR methods.  Flag anomalies with timestamps "
        "and severity scores.  Achieve precision > 80% and recall > 70%."
    ),
    difficulty="hard",
    required_skills=["pandas", "numpy", "statistics", "anomaly_detection"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb011_anomaly.py",
        "min_precision": 0.80,
        "min_recall": 0.70,
    },
    timeout_seconds=180,
)

# ---------------------------------------------------------------------------
# Web (2 tasks)
# ---------------------------------------------------------------------------

_WEB_01 = BenchmarkTask(
    task_id="SB-012",
    name="REST API Client",
    category=BenchmarkTaskCategory.WEB,
    description=(
        "Build an HTTP client that authenticates via OAuth2, paginates through "
        "API results, handles rate limiting with exponential backoff, and "
        "retries on transient errors.  Output collected records as JSON."
    ),
    difficulty="medium",
    required_skills=["http", "oauth2", "json", "retry_logic"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb012_rest_client.py",
    },
    timeout_seconds=120,
)

_WEB_02 = BenchmarkTask(
    task_id="SB-013",
    name="HTML Table Parser",
    category=BenchmarkTaskCategory.WEB,
    description=(
        "Parse an HTML page containing multiple nested tables.  Extract "
        "structured data preserving row/column relationships, handle "
        "colspan and rowspan attributes, and output as a list of dicts."
    ),
    difficulty="easy",
    required_skills=["html_parsing", "beautifulsoup"],
    verification_type="output_match",
    verification_config={
        "expected_structure": "list_of_dicts",
        "min_rows": 5,
    },
    timeout_seconds=90,
)

# ---------------------------------------------------------------------------
# System administration (2 tasks)
# ---------------------------------------------------------------------------

_SYS_01 = BenchmarkTask(
    task_id="SB-014",
    name="Log File Analysis",
    category=BenchmarkTaskCategory.SYSTEM_ADMIN,
    description=(
        "Parse structured log files in multiple formats (syslog, JSON lines, "
        "Apache combined).  Extract error rates, top IP addresses, response "
        "time percentiles, and generate a summary report."
    ),
    difficulty="medium",
    required_skills=["log_parsing", "regex", "statistics"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb014_log_analysis.py",
        "formats": ["syslog", "jsonl", "apache_combined"],
    },
    timeout_seconds=120,
)

_SYS_02 = BenchmarkTask(
    task_id="SB-015",
    name="Disk Usage Reporter",
    category=BenchmarkTaskCategory.SYSTEM_ADMIN,
    description=(
        "Scan a directory tree and report disk usage per directory, identify "
        "the top 10 largest files, detect duplicate files by content hash, "
        "and output results as structured JSON."
    ),
    difficulty="easy",
    required_skills=["filesystem", "hashing"],
    verification_type="file_check",
    verification_config={
        "output_file": "disk_usage_report.json",
        "required_keys": ["total_bytes", "top_files", "duplicates"],
    },
    timeout_seconds=120,
)

# ---------------------------------------------------------------------------
# DevOps (2 tasks)
# ---------------------------------------------------------------------------

_OPS_01 = BenchmarkTask(
    task_id="SB-016",
    name="Dockerfile Optimizer",
    category=BenchmarkTaskCategory.DEVOPS,
    description=(
        "Analyze a Dockerfile and suggest optimizations: layer caching "
        "improvements, multi-stage build opportunities, security hardening "
        "(non-root user, minimal base image), and reduced image size.  "
        "Output an optimized Dockerfile."
    ),
    difficulty="medium",
    required_skills=["docker", "security", "optimization"],
    verification_type="file_check",
    verification_config={
        "output_file": "Dockerfile.optimized",
        "required_directives": ["FROM", "USER", "COPY"],
    },
    timeout_seconds=120,
)

_OPS_02 = BenchmarkTask(
    task_id="SB-017",
    name="CI Pipeline YAML Generator",
    category=BenchmarkTaskCategory.DEVOPS,
    description=(
        "Generate a GitHub Actions workflow YAML that runs tests, lints, "
        "builds a Docker image, and deploys to staging.  Include caching, "
        "matrix builds for Python 3.11/3.12, and failure notifications."
    ),
    difficulty="medium",
    required_skills=["github_actions", "yaml", "ci_cd"],
    verification_type="file_check",
    verification_config={
        "output_file": ".github/workflows/ci.yml",
        "required_keys": ["jobs", "on"],
    },
    timeout_seconds=120,
)

# ---------------------------------------------------------------------------
# AI/ML (2 tasks)
# ---------------------------------------------------------------------------

_ML_01 = BenchmarkTask(
    task_id="SB-018",
    name="Text Classification Pipeline",
    category=BenchmarkTaskCategory.AI_ML,
    description=(
        "Build a text classification pipeline using TF-IDF vectorization "
        "and logistic regression.  Train on a labeled dataset, evaluate "
        "with cross-validation, and report precision/recall/F1 per class."
    ),
    difficulty="medium",
    required_skills=["scikit_learn", "nlp", "text_processing"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb018_text_classifier.py",
        "min_f1": 0.70,
    },
    timeout_seconds=180,
)

_ML_02 = BenchmarkTask(
    task_id="SB-019",
    name="Feature Importance Analysis",
    category=BenchmarkTaskCategory.AI_ML,
    description=(
        "Train a random forest model on a tabular dataset and compute "
        "feature importances using both MDI (Mean Decrease in Impurity) "
        "and permutation importance.  Compare rankings and identify "
        "the top 5 features by each method."
    ),
    difficulty="medium",
    required_skills=["scikit_learn", "numpy", "feature_engineering"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb019_feature_importance.py",
        "top_k": 5,
    },
    timeout_seconds=180,
)

# ---------------------------------------------------------------------------
# General (1 task)
# ---------------------------------------------------------------------------

_GEN_01 = BenchmarkTask(
    task_id="SB-020",
    name="JSON Schema Validator",
    category=BenchmarkTaskCategory.GENERAL,
    description=(
        "Implement a JSON Schema Draft 7 validator that supports type "
        "validation, required properties, pattern matching, enum constraints, "
        "and nested object/array validation.  Return detailed error messages "
        "for each validation failure."
    ),
    difficulty="medium",
    required_skills=["json", "schema_validation", "regex"],
    verification_type="pytest",
    verification_config={
        "test_file": "tests/test_sb020_json_schema.py",
    },
    timeout_seconds=120,
)

# ---------------------------------------------------------------------------
# Assembled catalog
# ---------------------------------------------------------------------------

DEFAULT_BENCHMARK_CATALOG: list[BenchmarkTask] = [
    # Scientific computing (3)
    _SCI_01,
    _SCI_02,
    _SCI_03,
    # Security (2)
    _SEC_01,
    _SEC_02,
    # Finance (2)
    _FIN_01,
    _FIN_02,
    # Media (2)
    _MED_01,
    _MED_02,
    # Data analysis (2)
    _DATA_01,
    _DATA_02,
    # Web (2)
    _WEB_01,
    _WEB_02,
    # System admin (2)
    _SYS_01,
    _SYS_02,
    # DevOps (2)
    _OPS_01,
    _OPS_02,
    # AI/ML (2)
    _ML_01,
    _ML_02,
    # General (1)
    _GEN_01,
]
