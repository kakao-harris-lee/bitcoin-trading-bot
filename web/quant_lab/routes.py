"""Flask blueprint for Quant Lab."""
from flask import Blueprint, render_template, request, jsonify, Response
from functools import wraps
import uuid
import json
import os
import re
from pathlib import Path
from typing import Dict, Any

from .worker.tasks import OptimizationJob, JobStatus
from .optimizer.study_manager import StudyManager
from .optimizer.search_space import (
    REGIMES, ENTRY_COMPONENTS, EXIT_COMPONENTS, COMPONENT_PARAMS,
    MLP_ENTRY_PARAMS, MLP_EXIT_PARAMS, MLP_ENSEMBLE_PARAMS, MLP_ADAPTER_PARAMS,
    REGIME_THRESHOLD_PARAMS,
)

quant_lab_bp = Blueprint(
    'quant_lab',
    __name__,
    template_folder='../templates/quant_lab',
    static_folder='../static/quant_lab',
)


# =============================================================================
# Security: Authentication
# =============================================================================

def _check_auth(username: str, password: str) -> bool:
    """Check if username/password is valid."""
    expected_user = os.environ.get('DASHBOARD_USERNAME', 'admin')
    expected_pass = os.environ.get('DASHBOARD_PASSWORD')
    if not expected_pass:
        return False  # No password set = deny all
    return username == expected_user and password == expected_pass


def _authenticate():
    """Return 401 response."""
    return Response(
        'Authentication required.', 401,
        {'WWW-Authenticate': 'Basic realm="Quant Lab"'}
    )


def requires_auth(f):
    """Decorator for routes that require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_auth(auth.username, auth.password):
            return _authenticate()
        return f(*args, **kwargs)
    return decorated


# =============================================================================
# Security: Input Validation
# =============================================================================

# Resource limits
MAX_TRIALS = 5000
MAX_HOURS = 48
MIN_TRIALS = 1

# Allowed data directory (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
ALLOWED_DATA_DIRS = [
    PROJECT_ROOT / "data",
]


def sanitize_strategy_name(name: str) -> str:
    """Sanitize strategy name to prevent path traversal.

    Only allows alphanumeric characters, underscores, and hyphens.
    Raises ValueError if name contains invalid characters.
    """
    if not name:
        raise ValueError("Strategy name cannot be empty")

    # Only allow alphanumeric, underscore, hyphen
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise ValueError(
            f"Invalid strategy name: '{name}'. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )

    # Prevent names that could be confused with paths
    if name.startswith('.') or name.startswith('-'):
        raise ValueError(f"Strategy name cannot start with '.' or '-': '{name}'")

    return name


def validate_data_path(data_path: str) -> str:
    """Validate data path to prevent path traversal.

    Ensures the path resolves to within allowed data directories.
    Returns the resolved absolute path if valid.
    Raises ValueError if path is outside allowed directories.
    """
    if not data_path:
        data_path = "data/binance_bitcoin.db"

    # Resolve the path relative to project root
    if not os.path.isabs(data_path):
        resolved = (PROJECT_ROOT / data_path).resolve()
    else:
        resolved = Path(data_path).resolve()

    # Check if path is within allowed directories using proper containment check
    # (string prefix check is vulnerable to sibling directory attacks like data_evil/)
    def _is_path_within(path: Path, allowed_dir: Path) -> bool:
        try:
            path.relative_to(allowed_dir)
            return True
        except ValueError:
            return False

    is_allowed = any(
        _is_path_within(resolved, allowed_dir)
        for allowed_dir in ALLOWED_DATA_DIRS
    )

    if not is_allowed:
        raise ValueError(
            f"Data path must be within allowed directories: {data_path}"
        )

    return str(resolved)


# Experiment templates
TEMPLATES = {
    "full_regime_search": {
        "name": "Full Regime Search",
        "description": "All Entry/Exit combinations across all 7 regimes",
        "config": {regime: {"entries": ENTRY_COMPONENTS, "exits": EXIT_COMPONENTS} for regime in REGIMES},
    },
    "conservative_search": {
        "name": "Conservative Search",
        "description": "Excludes 'None' option, ensures always-in-market",
        "config": {
            regime: {
                "entries": [e for e in ENTRY_COMPONENTS if e != "None"],
                "exits": EXIT_COMPONENTS,
            }
            for regime in REGIMES
        },
    },
    "bear_market_focus": {
        "name": "Bear Market Focus",
        "description": "Only optimizes BEAR_MODERATE and BEAR_STRONG regimes",
        "config": {
            regime: {
                "entries": ENTRY_COMPONENTS if "BEAR" in regime else ["SidewaysEntry"],
                "exits": EXIT_COMPONENTS if "BEAR" in regime else ["SidewaysExit"],
            }
            for regime in REGIMES
        },
    },
}


@quant_lab_bp.route('/')
def index():
    """Render main Quant Lab page."""
    return render_template('designer.html', regimes=REGIMES)


@quant_lab_bp.route('/api/templates')
@requires_auth
def get_templates():
    """Get available experiment templates."""
    return jsonify({"templates": TEMPLATES})


@quant_lab_bp.route('/api/search-space')
@requires_auth
def get_search_space():
    """Get search space configuration options."""
    return jsonify({
        "regimes": REGIMES,
        "entry_components": ENTRY_COMPONENTS,
        "exit_components": EXIT_COMPONENTS,
        "component_params": COMPONENT_PARAMS,
        "mlp_direction": {
            "entry_params": MLP_ENTRY_PARAMS,
            "exit_params": MLP_EXIT_PARAMS,
            "ensemble_params": MLP_ENSEMBLE_PARAMS,
            "adapter_params": MLP_ADAPTER_PARAMS,
        },
    })


@quant_lab_bp.route('/api/experiments', methods=['POST'])
@requires_auth
def create_experiment():
    """Create a new optimization experiment."""
    data = request.get_json()

    # Generate job ID (full UUID for security)
    job_id = str(uuid.uuid4())

    # Validate and sanitize study name
    study_name = data.get('study_name', '').strip()
    if not study_name:
        study_name = f'experiment_{job_id[:8]}'
    else:
        try:
            study_name = sanitize_strategy_name(study_name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    # Validate data path (prevent path traversal)
    try:
        validated_data_path = validate_data_path(
            data.get('data_path', 'data/binance_bitcoin.db')
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Validate and limit resource consumption
    max_trials = min(data.get('max_trials', 500), MAX_TRIALS)
    max_trials = max(max_trials, MIN_TRIALS)

    max_hours = data.get('max_hours')
    if max_hours is not None:
        max_hours = min(float(max_hours), MAX_HOURS)
        max_hours = max(max_hours, 0.1)

    # Determine strategy type
    strategy_type = data.get('strategy_type', 'regime')
    if strategy_type not in ('regime', 'mlp_direction'):
        return jsonify({"error": f"Invalid strategy_type: '{strategy_type}'"}), 400

    asset = data.get('asset')
    if strategy_type == 'mlp_direction' and not asset:
        return jsonify({"error": "MLP optimization requires 'asset' field (BTC, ETH, SOL)"}), 400
    if asset and asset.upper() not in ('BTC', 'ETH', 'SOL'):
        return jsonify({"error": f"Invalid asset: '{asset}'. Must be BTC, ETH, or SOL"}), 400

    # Create job
    job = OptimizationJob(
        job_id=job_id,
        study_name=study_name,
        data_path=validated_data_path,
        start_date=data['start_date'],
        end_date=data['end_date'],
        symbols=data.get('symbols', [asset.upper()] if asset else ['BTC']),
        max_trials=max_trials,
        max_hours=max_hours,
        search_config=data.get('search_config'),
        constraints=data.get('constraints'),
        mlflow_experiment=data.get('mlflow_experiment', 'quant_lab'),
        strategy_type=strategy_type,
        asset=asset.upper() if asset else None,
        config_path=data.get('config_path', 'config/strategies/allocation.json'),
    )

    # Enqueue job
    try:
        from redis import Redis
        from rq import Queue

        redis_conn = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
        q = Queue('quant_lab', connection=redis_conn)

        from .worker.tasks import run_optimization
        rq_job = q.enqueue(run_optimization, job, job_timeout='12h')

        return jsonify({
            "job_id": job_id,
            "rq_job_id": rq_job.id,
            "status": "queued",
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/experiments/<job_id>')
@requires_auth
def get_experiment_status(job_id: str):
    """Get status of an optimization experiment."""
    try:
        from redis import Redis

        redis_conn = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
        data = redis_conn.hgetall(f'quant_lab:job:{job_id}')

        if not data:
            return jsonify({"error": "Job not found"}), 404

        return jsonify({k.decode(): json.loads(v.decode()) for k, v in data.items()})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/experiments')
@requires_auth
def list_experiments():
    """List all experiments."""
    try:
        manager = StudyManager()
        studies = manager.list_studies()

        return jsonify({
            "experiments": [
                {
                    "study_name": s.study_name,
                    "n_trials": s.n_trials,
                    "datetime_start": s.datetime_start.isoformat() if s.datetime_start else None,
                }
                for s in studies
            ]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/active-jobs')
@requires_auth
def list_active_jobs():
    """List all active jobs from Redis."""
    try:
        from redis import Redis

        redis_conn = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))

        # Find all quant_lab:job:* keys
        job_keys = redis_conn.keys('quant_lab:job:*')
        active_jobs = []

        for key in job_keys:
            data = redis_conn.hgetall(key)
            if data:
                job_data = {k.decode(): json.loads(v.decode()) for k, v in data.items()}
                # Extract job_id from key
                job_id = key.decode().split(':')[-1]
                job_data['job_id'] = job_id

                # Only include running/pending jobs
                if job_data.get('status') in ['running', 'pending', 'queued']:
                    active_jobs.append(job_data)

        return jsonify({"active_jobs": active_jobs})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/experiments/<study_name>/results')
@requires_auth
def get_experiment_results(study_name: str):
    """Get results for an experiment."""
    try:
        manager = StudyManager()
        stats = manager.get_study_stats(study_name)
        pareto = manager.get_pareto_front(study_name)

        return jsonify({
            "stats": stats,
            "pareto_front": [
                {
                    "trial_number": t.number,
                    "values": {
                        "win_rate": t.values[0],
                        "total_return": t.values[1],
                        "max_drawdown": t.values[2],
                    },
                    "params": t.params,
                }
                for t in pareto
            ],
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/monitor')
def monitor():
    """Render job monitor page."""
    return render_template('monitor.html')


@quant_lab_bp.route('/results/<study_name>')
def results(study_name: str):
    """Render results page for a study."""
    return render_template('results.html', study_name=study_name)


@quant_lab_bp.route('/api/experiments/<study_name>/trials/<int:trial_number>/apply', methods=['POST'])
@requires_auth
def apply_trial_config(study_name: str, trial_number: int):
    """Apply a trial's configuration to allocation.json.

    Creates a new tuned strategy configuration based on the trial's
    optimized parameters and adds it to allocation.json.
    """
    try:
        from datetime import datetime
        import shutil

        data = request.get_json() or {}
        raw_strategy_name = data.get('strategy_name', f'tuned_{study_name}_{trial_number}')

        # Sanitize strategy name to prevent path traversal
        try:
            strategy_name = sanitize_strategy_name(raw_strategy_name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        # Get the trial from the study
        manager = StudyManager()
        trial = manager.get_trial(study_name, trial_number)

        if not trial:
            return jsonify({"error": f"Trial {trial_number} not found in study {study_name}"}), 404

        # Detect strategy type from trial params
        is_mlp = any(k.startswith(('entry_', 'exit_', 'ensemble_', 'adapter_'))
                      for k in trial.params)

        if is_mlp:
            tuned_config = _transform_mlp_trial_to_config(trial.params, trial.values)
        else:
            tuned_config = _transform_trial_to_config(trial.params, trial.values)

        tuned_config['study_name'] = study_name
        tuned_config['trial_number'] = trial_number
        tuned_config['applied_at'] = datetime.now().isoformat()

        # Save to config/tuned/ directory
        config_dir = os.path.join(os.path.dirname(__file__), '../../config/tuned')
        os.makedirs(config_dir, exist_ok=True)

        tuned_file = os.path.join(config_dir, f'{strategy_name}.json')
        with open(tuned_file, 'w') as f:
            json.dump(tuned_config, f, indent=2)

        # Load current allocation.json
        allocation_path = os.path.join(os.path.dirname(__file__), '../../config/strategies/allocation.json')

        with open(allocation_path, 'r') as f:
            allocation = json.load(f)

        # Backup allocation.json before modifying
        backup_path = allocation_path + f'.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy(allocation_path, backup_path)

        if is_mlp:
            # MLP: update existing strategy config with tuned params
            target_strategy = data.get('target_strategy', strategy_name)
            if target_strategy in allocation['strategies']:
                strat = allocation['strategies'][target_strategy]
            else:
                strat = allocation['strategies'].setdefault(target_strategy, {
                    'market': 'spot',
                    'entry': {'class': 'MLPDirectionEntryStrategy', 'params': {}},
                    'exit': {'class': 'MLPDirectionExitStrategy', 'params': {}},
                })

            # Apply entry params
            entry_params = strat.get('entry', {}).get('params', {})
            entry_params.update(tuned_config.get('entry_params', {}))
            strat.setdefault('entry', {})['params'] = entry_params

            # Apply exit params
            exit_params = strat.get('exit', {}).get('params', {})
            exit_params.update(tuned_config.get('exit_params', {}))
            strat.setdefault('exit', {})['params'] = exit_params

            # Apply ensemble weights
            if 'ensemble_weights' in tuned_config:
                ensemble = strat.get('ensemble_models', [])
                weights = tuned_config['ensemble_weights']
                weight_keys = ['weight_bwin3', 'weight_bwin4', 'weight_bwin5', 'weight_bwin7']
                for i, key in enumerate(weight_keys):
                    if i < len(ensemble) and key in weights:
                        ensemble[i]['weight'] = weights[key]

            # Apply adapter params
            for key, val in tuned_config.get('adapter_params', {}).items():
                strat[key] = val

            strat['tuned_config'] = f'config/tuned/{strategy_name}.json'
        else:
            # Regime: add as new strategy
            allocation['strategies'][strategy_name] = {
                'market': 'futures',
                'leverage': 3,
                'dynamic_sizing': True,
                'position_pct': 0.10,
                'position_size': 0.01,
                'use_smart_exit': True,
                'tuned_config': f'config/tuned/{strategy_name}.json',
                'regime_routing': tuned_config.get('regime_routing', {}),
            }

        # Save updated allocation.json
        with open(allocation_path, 'w') as f:
            json.dump(allocation, f, indent=2)

        return jsonify({
            "success": True,
            "strategy_name": strategy_name,
            "tuned_file": tuned_file,
            "backup_file": backup_path,
            "message": f"Applied trial {trial_number} as strategy '{strategy_name}'",
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _transform_trial_to_config(params: Dict[str, Any], values: tuple) -> Dict[str, Any]:
    """Transform Optuna trial params to structured config format.

    Converts flat params like:
        BULL_STRONG_entry: "ShortEntry"
        BULL_STRONG_exit: "ShortExit"
        BULL_STRONG_ShortEntry_rsi_overbought: 75.0

    To structured format:
        regime_routing:
            BULL_STRONG:
                entry: ShortEntry
                exit: ShortExit
                entry_params: {rsi_overbought: 75.0}
    """
    config = {
        'metrics': {
            'win_rate': values[0] if len(values) > 0 else None,
            'total_return': values[1] if len(values) > 1 else None,
            'max_drawdown': values[2] if len(values) > 2 else None,
        },
        'regime_routing': {},
    }

    # Parse regime-based params
    for regime in REGIMES:
        entry_key = f'{regime}_entry'
        exit_key = f'{regime}_exit'

        if entry_key in params:
            entry_component = params[entry_key]
            exit_component = params.get(exit_key, 'ShortExit')

            regime_config = {
                'entry': entry_component,
                'exit': exit_component,
                'entry_params': {},
                'exit_params': {},
            }

            # Extract component-specific params
            for key, value in params.items():
                # Entry params: REGIME_Component_param
                if key.startswith(f'{regime}_{entry_component}_'):
                    param_name = key.replace(f'{regime}_{entry_component}_', '')
                    regime_config['entry_params'][param_name] = value
                # Exit params: REGIME_Component_param
                elif key.startswith(f'{regime}_{exit_component}_'):
                    param_name = key.replace(f'{regime}_{exit_component}_', '')
                    regime_config['exit_params'][param_name] = value

            config['regime_routing'][regime] = regime_config

    # Extract regime classification thresholds (regime_mfi_bull_strong → mfi_bull_strong)
    regime_thresholds = {}
    for key, value in params.items():
        if key.startswith('regime_') and key[len('regime_'):] in REGIME_THRESHOLD_PARAMS:
            regime_thresholds[key[len('regime_'):]] = value
    if regime_thresholds:
        config['regime_thresholds'] = regime_thresholds

    return config


def _transform_mlp_trial_to_config(params: Dict[str, Any], values: tuple) -> Dict[str, Any]:
    """Transform MLP Optuna trial params to structured config format.

    Converts flat params like:
        entry_buy_confidence_threshold: 0.3
        exit_stop_loss_pct: 10.0
        ensemble_weight_bwin3: 0.15
        adapter_cash_in_bear: True

    To structured format with entry_params, exit_params, ensemble_weights, adapter_params.
    """
    config: Dict[str, Any] = {
        'strategy_type': 'mlp_direction',
        'metrics': {
            'win_rate': values[0] if len(values) > 0 else None,
            'total_return': values[1] if len(values) > 1 else None,
            'max_drawdown': values[2] if len(values) > 2 else None,
        },
        'entry_params': {},
        'exit_params': {},
        'ensemble_weights': {},
        'adapter_params': {},
    }

    regime_thresholds = {}
    for key, value in params.items():
        if key.startswith('entry_'):
            config['entry_params'][key[len('entry_'):]] = value
        elif key.startswith('exit_'):
            config['exit_params'][key[len('exit_'):]] = value
        elif key.startswith('ensemble_'):
            config['ensemble_weights'][key[len('ensemble_'):]] = value
        elif key.startswith('adapter_'):
            config['adapter_params'][key[len('adapter_'):]] = value
        elif key.startswith('regime_') and key[len('regime_'):] in REGIME_THRESHOLD_PARAMS:
            regime_thresholds[key[len('regime_'):]] = value

    if regime_thresholds:
        config['regime_thresholds'] = regime_thresholds

    return config


# =============================================================================
# Backtest CSV Log Download API
# =============================================================================

# Allowed log directory (relative to project root)
BACKTEST_LOG_DIR = PROJECT_ROOT / "backtest_logs"


def _validate_log_filename(filename: str) -> bool:
    """Validate log filename to prevent path traversal.

    Only allows alphanumeric characters, underscores, hyphens, and .csv extension.
    """
    if not filename:
        return False

    # Only allow safe characters
    if not re.match(r'^[a-zA-Z0-9_\-]+\.csv$', filename):
        return False

    # No path separators
    if '/' in filename or '\\' in filename:
        return False

    return True


@quant_lab_bp.route('/api/backtest/logs')
@requires_auth
def list_backtest_logs():
    """List available backtest CSV log files.

    Returns:
        JSON with list of log files and metadata.
    """
    try:
        from core.backtest_logger import BacktestLogger

        logs = BacktestLogger.list_logs(str(BACKTEST_LOG_DIR))

        return jsonify({
            "logs": logs,
            "count": len(logs),
            "directory": str(BACKTEST_LOG_DIR),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/backtest/logs/<filename>/download')
@requires_auth
def download_backtest_log(filename: str):
    """Download a backtest CSV log file.

    Args:
        filename: Name of the CSV file to download.

    Returns:
        CSV file as attachment.
    """
    from flask import send_file

    # Validate filename (prevent path traversal)
    if not _validate_log_filename(filename):
        return jsonify({"error": "Invalid filename"}), 400

    filepath = BACKTEST_LOG_DIR / filename

    # Verify file exists and is within allowed directory
    try:
        resolved = filepath.resolve()
        resolved.relative_to(BACKTEST_LOG_DIR.resolve())
    except (ValueError, OSError):
        return jsonify({"error": "Invalid file path"}), 400

    if not resolved.exists():
        return jsonify({"error": "File not found"}), 404

    if not resolved.is_file():
        return jsonify({"error": "Not a file"}), 400

    return send_file(
        resolved,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )


@quant_lab_bp.route('/api/backtest/logs/<filename>')
@requires_auth
def get_backtest_log_info(filename: str):
    """Get metadata for a specific backtest log file.

    Args:
        filename: Name of the CSV file.

    Returns:
        JSON with file metadata.
    """
    from datetime import datetime

    # Validate filename
    if not _validate_log_filename(filename):
        return jsonify({"error": "Invalid filename"}), 400

    filepath = BACKTEST_LOG_DIR / filename

    # Verify file exists
    try:
        resolved = filepath.resolve()
        resolved.relative_to(BACKTEST_LOG_DIR.resolve())
    except (ValueError, OSError):
        return jsonify({"error": "Invalid file path"}), 400

    if not resolved.exists():
        return jsonify({"error": "File not found"}), 404

    stat = resolved.stat()

    # Count lines (rows)
    with open(resolved, 'r') as f:
        row_count = sum(1 for _ in f) - 1  # Subtract header

    return jsonify({
        "filename": filename,
        "filepath": str(resolved),
        "size_kb": round(stat.st_size / 1024, 2),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "row_count": row_count,
    })
