"""
Security utilities for enhanced API protection
"""
from __future__ import annotations
import time
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from functools import wraps
from flask import request, jsonify, current_app, g
import logging

logger = logging.getLogger(__name__)

# In-memory rate limiting store (in production, use Redis or similar)
rate_limit_store: Dict[str, Dict[str, Any]] = {}

class RateLimiter:
    """简单的滑动窗口速率限制器"""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    def is_allowed(self, client_key: str) -> tuple[bool, Dict[str, Any]]:
        """检查是否允许请求"""
        now = time.time()
        
        if client_key not in rate_limit_store:
            rate_limit_store[client_key] = {
                'requests': [],
                'blocked_until': 0
            }
        
        client_data = rate_limit_store[client_key]
        
        # 检查是否仍在封禁期
        if client_data['blocked_until'] > now:
            remaining_time = int(client_data['blocked_until'] - now)
            return False, {
                'error': 'Rate limit exceeded',
                'retry_after': remaining_time,
                'blocked_until': datetime.fromtimestamp(client_data['blocked_until']).isoformat()
            }
        
        # 清理过期的请求记录
        cutoff_time = now - self.window_seconds
        client_data['requests'] = [req_time for req_time in client_data['requests'] if req_time > cutoff_time]
        
        # 检查是否超过限制
        if len(client_data['requests']) >= self.max_requests:
            # 封禁30分钟
            client_data['blocked_until'] = now + 1800  # 30 minutes
            return False, {
                'error': 'Rate limit exceeded',
                'retry_after': 1800,
                'requests_in_window': len(client_data['requests']),
                'max_requests': self.max_requests
            }
        
        # 记录当前请求
        client_data['requests'].append(now)
        
        return True, {
            'requests_in_window': len(client_data['requests']),
            'max_requests': self.max_requests,
            'window_seconds': self.window_seconds,
            'reset_time': datetime.fromtimestamp(cutoff_time + self.window_seconds).isoformat()
        }


# 默认速率限制器实例
default_rate_limiter = RateLimiter(max_requests=1000, window_seconds=3600)  # 1000 requests per hour
strict_rate_limiter = RateLimiter(max_requests=100, window_seconds=3600)    # 100 requests per hour for sensitive operations


def rate_limit(limiter: Optional[RateLimiter] = None):
    """速率限制装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            nonlocal limiter
            if limiter is None:
                limiter = default_rate_limiter
                
            # 使用API key或IP地址作为客户端标识
            client_key = None
            if hasattr(request, 'current_device') and request.current_device:
                client_key = f"device_{request.current_device.device_no}"
            else:
                api_key = request.headers.get('X-API-Key')
                if api_key:
                    client_key = f"api_{hashlib.md5(api_key.encode()).hexdigest()}"
                else:
                    client_key = f"ip_{request.remote_addr}"
            
            allowed, info = limiter.is_allowed(client_key)
            
            if not allowed:
                response = jsonify({
                    "error": info['error'],
                    "code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": info['retry_after']
                })
                response.headers['Retry-After'] = str(info['retry_after'])
                return response, 429
            
            # 添加速率限制头部
            g.rate_limit_info = info
            response = f(*args, **kwargs)
            
            # 如果返回值是JsonResponse，添加速率限制头部
            if hasattr(response, 'headers'):
                response.headers['X-RateLimit-Limit'] = str(info['max_requests'])
                response.headers['X-RateLimit-Remaining'] = str(info['max_requests'] - info['requests_in_window'])
                response.headers['X-RateLimit-Reset'] = info['reset_time']
            
            return response
            
        return decorated_function
    return decorator


class RequestSigner:
    """请求签名验证器"""
    
    @staticmethod
    def generate_signature(method: str, path: str, body: str, timestamp: str, api_key: str, secret_key: str) -> str:
        """生成请求签名"""
        # 构建签名字符串: METHOD|PATH|BODY|TIMESTAMP|API_KEY
        sign_string = f"{method.upper()}|{path}|{body}|{timestamp}|{api_key}"
        
        # 使用HMAC-SHA256生成签名
        signature = hmac.new(
            secret_key.encode('utf-8'),
            sign_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    @staticmethod
    def verify_signature(signature: str, method: str, path: str, body: str, timestamp: str, api_key: str, secret_key: str) -> bool:
        """验证请求签名"""
        expected_signature = RequestSigner.generate_signature(method, path, body, timestamp, api_key, secret_key)
        return hmac.compare_digest(signature, expected_signature)
    
    @staticmethod
    def is_timestamp_valid(timestamp: str, tolerance_seconds: int = 300) -> bool:
        """验证时间戳有效性（防重放攻击）"""
        try:
            request_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            current_time = datetime.utcnow().replace(tzinfo=request_time.tzinfo)
            
            time_diff = abs((current_time - request_time).total_seconds())
            return time_diff <= tolerance_seconds
            
        except (ValueError, TypeError):
            return False


def require_signature(f):
    """请求签名验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查是否启用签名验证
        if not current_app.config.get('ENABLE_REQUEST_SIGNATURE', False):
            return f(*args, **kwargs)
        
        # 获取签名相关头部
        signature = request.headers.get('X-Signature')
        timestamp = request.headers.get('X-Timestamp')
        api_key = request.headers.get('X-API-Key')
        
        if not all([signature, timestamp, api_key]):
            return jsonify({
                "error": "Missing signature headers",
                "code": "MISSING_SIGNATURE",
                "required_headers": ["X-Signature", "X-Timestamp", "X-API-Key"]
            }), 400
        
        # 验证时间戳
        if not RequestSigner.is_timestamp_valid(timestamp):
            return jsonify({
                "error": "Invalid or expired timestamp",
                "code": "INVALID_TIMESTAMP"
            }), 400
        
        # 获取请求体
        body = request.get_data(as_text=True) or ""
        
        # 获取设备的密钥（在实际应用中，应该从数据库获取）
        from ..models import Device
        device = Device.query.filter_by(api_key=api_key).first()
        if not device:
            return jsonify({
                "error": "Invalid API key",
                "code": "INVALID_API_KEY"
            }), 401
        
        # 使用设备的API key作为密钥（在生产环境中应该使用单独的签名密钥）
        secret_key = device.api_key
        
        # 验证签名
        if not RequestSigner.verify_signature(
            signature, request.method, request.path, body, timestamp, api_key, secret_key
        ):
            return jsonify({
                "error": "Invalid signature",
                "code": "INVALID_SIGNATURE"
            }), 403
        
        return f(*args, **kwargs)
    
    return decorated_function


def generate_api_key() -> str:
    """生成安全的API密钥"""
    return secrets.token_urlsafe(32)


def generate_device_secret() -> str:
    """生成设备专用密钥"""
    return secrets.token_urlsafe(64)


class SecurityAuditLogger:
    """安全审计日志记录器"""
    
    @staticmethod
    def log_security_event(event_type: str, details: Dict[str, Any], severity: str = 'info'):
        """记录安全事件"""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'severity': severity,
            'client_ip': request.remote_addr if request else None,
            'user_agent': request.headers.get('User-Agent') if request else None,
            'details': details
        }
        
        # 根据严重程度选择日志级别
        if severity == 'critical':
            logger.critical(f"Security Event: {event_type} - {details}")
        elif severity == 'warning':
            logger.warning(f"Security Event: {event_type} - {details}")
        else:
            logger.info(f"Security Event: {event_type} - {details}")
        
        # 在实际应用中，应该将安全事件存储到专用的安全日志表或外部安全系统
        try:
            from ..models import OperationLog
            from ..extensions import db
            
            # 记录到操作日志表
            audit_log = OperationLog(
                user_id=0,  # 系统事件
                action=f'security_{event_type}',
                target_type='security',
                target_id=None,
                ip=request.remote_addr if request else None,
                user_agent=request.headers.get('User-Agent') if request else None,
                raw_payload=log_entry
            )
            db.session.add(audit_log)
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Failed to log security event to database: {e}")


def audit_security_event(event_type: str, severity: str = 'info'):
    """安全事件审计装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = f(*args, **kwargs)
                
                # 记录成功事件
                SecurityAuditLogger.log_security_event(
                    event_type,
                    {
                        'function': f.__name__,
                        'success': True,
                        'duration_ms': int((time.time() - start_time) * 1000)
                    },
                    severity
                )
                
                return result
                
            except Exception as e:
                # 记录失败事件
                SecurityAuditLogger.log_security_event(
                    f"{event_type}_failed",
                    {
                        'function': f.__name__,
                        'success': False,
                        'error': str(e),
                        'duration_ms': int((time.time() - start_time) * 1000)
                    },
                    'warning'
                )
                raise
                
        return decorated_function
    return decorator


# 常用的安全配置
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'X-XSS-Protection': '1; mode=block',
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:;"
}


def add_security_headers(response):
    """添加安全头部"""
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    return response