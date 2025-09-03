/**
 * 咖啡机客户端通用JavaScript功能
 */

// 全局变量
window.CoffeeClient = {
    socket: null,
    config: {},
    status: {},
    intervals: {}
};

// 初始化函数
function initializeCoffeeClient() {
    console.log('初始化咖啡机客户端...');
    
    // 建立WebSocket连接
    if (typeof io !== 'undefined') {
        window.CoffeeClient.socket = io();
        setupWebSocketEvents();
    }
    
    // 设置通用事件监听器
    setupCommonEvents();
    
    // 加载配置
    loadClientConfig();
}

// 设置WebSocket事件
function setupWebSocketEvents() {
    const socket = window.CoffeeClient.socket;
    
    socket.on('connect', function() {
        console.log('WebSocket已连接');
        updateConnectionStatus(true);
    });
    
    socket.on('disconnect', function() {
        console.log('WebSocket已断开');
        updateConnectionStatus(false);
    });
    
    socket.on('status_update', function(data) {
        console.log('收到状态更新:', data);
        window.CoffeeClient.status = data;
        // 触发自定义事件
        document.dispatchEvent(new CustomEvent('coffeeStatusUpdate', { detail: data }));
    });
    
    socket.on('coffee_started', function(data) {
        showNotification('开始制作咖啡', 'success');
        document.dispatchEvent(new CustomEvent('coffeeStarted', { detail: data }));
    });
    
    socket.on('coffee_cancelled', function(data) {
        showNotification('制作已取消', 'warning');
        document.dispatchEvent(new CustomEvent('coffeeCancelled', { detail: data }));
    });
    
    socket.on('error', function(data) {
        console.error('WebSocket错误:', data);
        showNotification('发生错误: ' + data.message, 'danger');
    });
}

// 设置通用事件
function setupCommonEvents() {
    // 页面可见性变化
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            console.log('页面隐藏，暂停更新');
            pauseUpdates();
        } else {
            console.log('页面显示，恢复更新');
            resumeUpdates();
        }
    });
    
    // 网络状态变化
    window.addEventListener('online', function() {
        showNotification('网络连接已恢复', 'success');
        resumeUpdates();
    });
    
    window.addEventListener('offline', function() {
        showNotification('网络连接已断开', 'warning');
        pauseUpdates();
    });
}

// 加载客户端配置
async function loadClientConfig() {
    try {
        const response = await apiRequest('/api/config');
        if (response.success) {
            window.CoffeeClient.config = response.config;
            console.log('配置加载完成:', response.config);
        }
    } catch (error) {
        console.error('加载配置失败:', error);
    }
}

// API请求函数
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json'
        }
    };
    
    const finalOptions = { ...defaultOptions, ...options };
    
    try {
        const response = await fetch(url, finalOptions);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        } else {
            return { success: true, data: await response.text() };
        }
        
    } catch (error) {
        console.error('API请求失败:', url, error);
        return {
            success: false,
            error: error.message
        };
    }
}

// 连接状态管理
function updateConnectionStatus(connected) {
    const indicators = document.querySelectorAll('#connection-status, .connection-indicator');
    const texts = document.querySelectorAll('#connection-text, .connection-text');
    
    indicators.forEach(indicator => {
        if (connected) {
            indicator.className = indicator.className.replace('status-offline', 'status-online');
        } else {
            indicator.className = indicator.className.replace('status-online', 'status-offline');
        }
    });
    
    texts.forEach(text => {
        text.textContent = connected ? '在线' : '离线';
    });
}

// 通知系统
function showNotification(message, type = 'info', duration = 5000) {
    // 使用Toast显示通知
    showToast(message, type);
    
    // 如果支持，也显示系统通知
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('咖啡机客户端', {
            body: message,
            icon: '/static/images/coffee-icon.png'
        });
    }
}

// Toast显示函数
function showToast(message, type = 'info', duration = 5000) {
    const toastContainer = getOrCreateToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="fas fa-${getToastIcon(type)} me-2"></i>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    // 使用Bootstrap Toast
    if (typeof bootstrap !== 'undefined') {
        const bsToast = new bootstrap.Toast(toast, { delay: duration });
        bsToast.show();
        
        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    } else {
        // 备用方案
        setTimeout(() => {
            toast.remove();
        }, duration);
    }
}

function getToastIcon(type) {
    const icons = {
        'success': 'check-circle',
        'info': 'info-circle',
        'warning': 'exclamation-triangle',
        'danger': 'exclamation-circle'
    };
    return icons[type] || 'info-circle';
}

function getOrCreateToastContainer() {
    let container = document.getElementById('toast-container');
    
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '1055';
        document.body.appendChild(container);
    }
    
    return container;
}

// 时间格式化函数
function formatTime(date) {
    if (typeof date === 'string') {
        date = new Date(date);
    }
    return date.toLocaleTimeString('zh-CN');
}

function formatDate(date) {
    if (typeof date === 'string') {
        date = new Date(date);
    }
    return date.toLocaleDateString('zh-CN');
}

function formatDateTime(date) {
    if (typeof date === 'string') {
        date = new Date(date);
    }
    return date.toLocaleString('zh-CN');
}

// 数值格式化函数
function formatTemperature(temp) {
    return `${parseFloat(temp).toFixed(1)}°C`;
}

function formatPressure(pressure) {
    return `${parseFloat(pressure).toFixed(1)}bar`;
}

function formatPercentage(value) {
    return `${parseFloat(value).toFixed(1)}%`;
}

// 更新控制
function pauseUpdates() {
    Object.values(window.CoffeeClient.intervals).forEach(interval => {
        if (interval) {
            clearInterval(interval);
        }
    });
    window.CoffeeClient.intervals = {};
}

function resumeUpdates() {
    // 重新启动必要的定时更新
    if (typeof startStatusUpdates === 'function') {
        startStatusUpdates();
    }
}

// 设备控制函数
async function startCoffee(coffeeType, customParams = {}) {
    const data = {
        coffee_type: coffeeType,
        custom_params: customParams
    };
    
    const response = await apiRequest('/api/coffee/start', {
        method: 'POST',
        body: JSON.stringify(data)
    });
    
    return response;
}

async function cancelCoffee() {
    const response = await apiRequest('/api/coffee/cancel', {
        method: 'POST'
    });
    
    return response;
}

async function getStatus() {
    const response = await apiRequest('/api/status');
    return response;
}

async function getHardwareStatus() {
    const response = await apiRequest('/api/hardware/status');
    return response;
}

// 主题切换
function switchTheme(theme) {
    document.body.className = document.body.className.replace(/theme-\w+/g, '');
    document.body.classList.add(`theme-${theme}`);
    
    localStorage.setItem('coffee-client-theme', theme);
}

function loadTheme() {
    const savedTheme = localStorage.getItem('coffee-client-theme') || 'dark';
    switchTheme(savedTheme);
}

// 本地存储管理
function saveToStorage(key, value) {
    try {
        localStorage.setItem(`coffee-client-${key}`, JSON.stringify(value));
        return true;
    } catch (error) {
        console.error('保存到本地存储失败:', error);
        return false;
    }
}

function loadFromStorage(key, defaultValue = null) {
    try {
        const item = localStorage.getItem(`coffee-client-${key}`);
        return item ? JSON.parse(item) : defaultValue;
    } catch (error) {
        console.error('从本地存储加载失败:', error);
        return defaultValue;
    }
}

// 音效播放（如果需要）
function playSound(soundType) {
    const sounds = {
        'success': '/static/sounds/success.mp3',
        'error': '/static/sounds/error.mp3',
        'notification': '/static/sounds/notification.mp3'
    };
    
    if (sounds[soundType] && window.CoffeeClient.config?.ui?.sound_enabled) {
        const audio = new Audio(sounds[soundType]);
        audio.volume = 0.5;
        audio.play().catch(error => {
            console.log('播放音效失败:', error);
        });
    }
}

// 请求通知权限
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                showToast('通知权限已获取', 'success');
            }
        });
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeCoffeeClient();
    loadTheme();
    requestNotificationPermission();
});

// 导出到全局作用域
window.apiRequest = apiRequest;
window.showToast = showToast;
window.showNotification = showNotification;
window.formatTime = formatTime;
window.formatDate = formatDate;
window.formatDateTime = formatDateTime;
window.formatTemperature = formatTemperature;
window.formatPressure = formatPressure;
window.formatPercentage = formatPercentage;
window.startCoffee = startCoffee;
window.cancelCoffee = cancelCoffee;
window.getStatus = getStatus;
window.getHardwareStatus = getHardwareStatus;