"""Flask blueprint for Quant Lab."""
from flask import Blueprint, render_template, request, jsonify
import uuid
import json
import os
from typing import Dict, Any

from .worker.tasks import OptimizationJob, JobStatus
from .optimizer.study_manager import StudyManager
from .optimizer.search_space import REGIMES, ENTRY_COMPONENTS, EXIT_COMPONENTS, COMPONENT_PARAMS

quant_lab_bp = Blueprint(
    'quant_lab',
    __name__,
    template_folder='../templates/quant_lab',
    static_folder='../static/quant_lab',
)


# Experiment templates
TEMPLATES = {
    "v35_param_sweep": {
        "name": "V35 Parameter Sweep",
        "description": "Fixed V35Entry/Exit for BULL regimes, tune params only",
        "config": {
            regime: {
                "entries": ["V35Entry"] if "BULL" in regime else ENTRY_COMPONENTS,
                "exits": ["V35TrailingExit"],
            }
            for regime in REGIMES
        },
    },
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
                "entries": ENTRY_COMPONENTS if "BEAR" in regime else ["V35Entry"],
                "exits": EXIT_COMPONENTS if "BEAR" in regime else ["V35TrailingExit"],
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
def get_templates():
    """Get available experiment templates."""
    return jsonify({"templates": TEMPLATES})


@quant_lab_bp.route('/api/search-space')
def get_search_space():
    """Get search space configuration options."""
    return jsonify({
        "regimes": REGIMES,
        "entry_components": ENTRY_COMPONENTS,
        "exit_components": EXIT_COMPONENTS,
        "component_params": COMPONENT_PARAMS,
    })


@quant_lab_bp.route('/api/experiments', methods=['POST'])
def create_experiment():
    """Create a new optimization experiment."""
    data = request.get_json()

    # Generate job ID
    job_id = str(uuid.uuid4())[:8]
    
    # Validate and sanitize study name
    study_name = data.get('study_name', '').strip()
    if not study_name:
        study_name = f'experiment_{job_id}'

    # Create job
    job = OptimizationJob(
        job_id=job_id,
        study_name=study_name,
        data_path=data.get('data_path', 'data/binance_bitcoin.db'),
        start_date=data['start_date'],
        end_date=data['end_date'],
        symbols=data['symbols'],
        max_trials=data.get('max_trials', 500),
        max_hours=data.get('max_hours'),
        search_config=data.get('search_config'),
        constraints=data.get('constraints'),
        mlflow_experiment=data.get('mlflow_experiment', 'quant_lab'),
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
def apply_trial_config(study_name: str, trial_number: int):
    """Apply a trial's configuration to allocation.json.

    Creates a new tuned strategy configuration based on the trial's
    optimized parameters and adds it to allocation.json.
    """
    try:
        from datetime import datetime
        import shutil

        data = request.get_json() or {}
        strategy_name = data.get('strategy_name', f'tuned_{study_name}_{trial_number}')

        # Get the trial from the study
        manager = StudyManager()
        trial = manager.get_trial(study_name, trial_number)

        if not trial:
            return jsonify({"error": f"Trial {trial_number} not found in study {study_name}"}), 404

        # Transform Optuna flat params to structured config
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

        # Add or update the strategy in allocation.json
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
        BULL_STRONG_entry: "V35Entry"
        BULL_STRONG_exit: "V35TrailingExit"
        BULL_STRONG_V35Entry_mfi_threshold: 55.0

    To structured format:
        regime_routing:
            BULL_STRONG:
                entry: V35Entry
                exit: V35TrailingExit
                entry_params: {mfi_threshold: 55.0}
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
            exit_component = params.get(exit_key, 'V35TrailingExit')

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

    return config
