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

    # Create job
    job = OptimizationJob(
        job_id=job_id,
        study_name=data.get('study_name', f'experiment_{job_id}'),
        data_path=data.get('data_path', 'data/binance.db'),
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
