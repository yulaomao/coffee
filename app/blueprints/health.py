"""
Health check and system monitoring endpoints.
"""
from datetime import datetime
from flask import Blueprint, jsonify
from ..extensions import db
from ..utils.logging_utils import get_logger, performance_logger

bp = Blueprint('health', __name__, url_prefix='/api')
logger = get_logger('health')


@bp.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    start_time = datetime.utcnow()
    
    try:
        # Check database connectivity
        db.session.execute(db.text('SELECT 1'))
        database_status = 'healthy'
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        database_status = 'unhealthy'
    
    # Calculate response time
    response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
    
    health_status = {
        'status': 'healthy' if database_status == 'healthy' else 'unhealthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0',
        'services': {
            'database': database_status,
            'application': 'healthy'
        },
        'response_time_ms': round(response_time, 2)
    }
    
    # Log performance
    performance_logger.log_request_timing(
        '/api/health', 'GET', response_time, 
        200 if health_status['status'] == 'healthy' else 503
    )
    
    status_code = 200 if health_status['status'] == 'healthy' else 503
    return jsonify(health_status), status_code


@bp.route('/metrics', methods=['GET'])
def system_metrics():
    """System metrics endpoint for monitoring."""
    try:
        from ..models import Device, Order, User
        
        metrics = {
            'timestamp': datetime.utcnow().isoformat(),
            'database': {
                'total_devices': Device.query.count(),
                'online_devices': Device.query.filter_by(status='online').count(),
                'total_orders': Order.query.count(),
                'total_users': User.query.count()
            },
            'system': {
                'uptime_seconds': 0,  # Would need startup tracking
                'memory_usage_mb': 0   # Would need psutil integration
            }
        }
        
        return jsonify(metrics)
        
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        return jsonify({'error': 'Metrics collection failed'}), 500