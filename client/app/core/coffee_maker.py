"""
咖啡制作控制模块

负责咖啡制作流程的协调和控制
"""
import logging
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Callable
from threading import Thread, Event, Lock
from .hardware import HardwareInterface

logger = logging.getLogger(__name__)

class CoffeeType(Enum):
    """咖啡类型"""
    ESPRESSO = "espresso"
    AMERICANO = "americano"
    LATTE = "latte"
    CAPPUCCINO = "cappuccino"
    MACCHIATO = "macchiato"

class BrewStatus(Enum):
    """制作状态"""
    IDLE = "idle"
    PREPARING = "preparing"
    GRINDING = "grinding"
    HEATING = "heating"
    BREWING = "brewing"
    STEAMING = "steaming"
    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"

class BrewStep:
    """制作步骤"""
    def __init__(self, name: str, duration: float, action: Callable = None):
        self.name = name
        self.duration = duration
        self.action = action
        self.start_time = None
        self.completed = False

class BrewJob:
    """制作任务"""
    def __init__(self, job_id: str, coffee_type: CoffeeType, recipe: Dict[str, Any]):
        self.job_id = job_id
        self.coffee_type = coffee_type
        self.recipe = recipe
        self.status = BrewStatus.IDLE
        self.steps = []
        self.current_step = 0
        self.start_time = None
        self.end_time = None
        self.error_message = None
        self.progress = 0.0

class CoffeeMaker:
    """咖啡机控制器"""
    
    def __init__(self, hardware: HardwareInterface, recipes: Dict[str, Dict[str, Any]]):
        self.hardware = hardware
        self.recipes = recipes
        self.current_job = None
        self.job_history = []
        self.lock = Lock()
        self.stop_event = Event()
        self.brew_thread = None
        self.status_callbacks = []
        self.initialized = False
    
    def initialize(self) -> bool:
        """初始化咖啡机"""
        logger.info("初始化咖啡机控制器...")
        
        if not self.hardware.initialize():
            logger.error("硬件初始化失败")
            return False
        
        self.initialized = True
        logger.info("咖啡机控制器初始化完成")
        return True
    
    def cleanup(self):
        """清理资源"""
        logger.info("清理咖啡机资源...")
        self.cancel_current_job()
        self.hardware.cleanup()
        self.initialized = False
        logger.info("咖啡机资源清理完成")
    
    def add_status_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """添加状态回调"""
        self.status_callbacks.append(callback)
    
    def _notify_status_change(self, status_data: Dict[str, Any]):
        """通知状态变化"""
        for callback in self.status_callbacks:
            try:
                callback(status_data)
            except Exception as e:
                logger.error(f"状态回调错误: {e}")
    
    def get_available_coffees(self) -> Dict[str, Dict[str, Any]]:
        """获取可用咖啡类型"""
        return self.recipes.copy()
    
    def get_machine_status(self) -> Dict[str, Any]:
        """获取咖啡机状态"""
        with self.lock:
            hardware_status = self.hardware.get_status() if hasattr(self.hardware, 'get_status') else {
                'temperature': self.hardware.get_temperature(),
                'water_level': self.hardware.get_water_level(),
                'pressure': self.hardware.get_pressure()
            }
            
            job_status = None
            if self.current_job:
                job_status = {
                    'job_id': self.current_job.job_id,
                    'coffee_type': self.current_job.coffee_type.value,
                    'status': self.current_job.status.value,
                    'progress': self.current_job.progress,
                    'current_step': self.current_job.steps[self.current_job.current_step].name if self.current_job.current_step < len(self.current_job.steps) else None
                }
            
            return {
                'initialized': self.initialized,
                'hardware': hardware_status,
                'current_job': job_status,
                'timestamp': datetime.now().isoformat()
            }
    
    def start_coffee(self, coffee_type: str, custom_params: Dict[str, Any] = None) -> Optional[str]:
        """开始制作咖啡"""
        if not self.initialized:
            logger.error("咖啡机未初始化")
            return None
        
        with self.lock:
            if self.current_job and self.current_job.status not in [BrewStatus.FINISHED, BrewStatus.ERROR, BrewStatus.CANCELLED]:
                logger.error("咖啡机正在制作中，无法开始新的制作")
                return None
            
            # 获取配方
            if coffee_type not in self.recipes:
                logger.error(f"未知的咖啡类型: {coffee_type}")
                return None
            
            recipe = self.recipes[coffee_type].copy()
            if custom_params:
                recipe.update(custom_params)
            
            # 创建制作任务
            job_id = str(uuid.uuid4())
            self.current_job = BrewJob(job_id, CoffeeType(coffee_type), recipe)
            
            # 构建制作步骤
            self._build_brew_steps(self.current_job)
            
            # 启动制作线程
            self.stop_event.clear()
            self.brew_thread = Thread(target=self._brew_process, args=(self.current_job,), daemon=True)
            self.brew_thread.start()
            
            logger.info(f"开始制作咖啡: {coffee_type}, 任务ID: {job_id}")
            return job_id
    
    def cancel_current_job(self):
        """取消当前制作"""
        with self.lock:
            if self.current_job and self.current_job.status not in [BrewStatus.FINISHED, BrewStatus.ERROR, BrewStatus.CANCELLED]:
                logger.info(f"取消制作任务: {self.current_job.job_id}")
                self.current_job.status = BrewStatus.CANCELLED
                self.stop_event.set()
                
                # 停止所有硬件组件
                self._stop_all_components()
    
    def _build_brew_steps(self, job: BrewJob):
        """构建制作步骤"""
        recipe = job.recipe
        steps = []
        
        # 准备阶段
        steps.append(BrewStep("准备阶段", 2.0, self._step_prepare))
        
        # 研磨咖啡豆
        grind_time = recipe.get('grind_time', 15)
        steps.append(BrewStep("研磨咖啡豆", grind_time, lambda: self._step_grind(grind_time)))
        
        # 加热水
        steps.append(BrewStep("加热水", 5.0, self._step_heat_water))
        
        # 萃取咖啡
        brew_time = recipe.get('brew_time', 25)
        steps.append(BrewStep("萃取咖啡", brew_time, lambda: self._step_brew_coffee(brew_time, recipe)))
        
        # 如果需要蒸汽（拿铁、卡布奇诺等）
        if 'steam_time' in recipe and recipe['steam_time'] > 0:
            steam_time = recipe['steam_time']
            steps.append(BrewStep("制作奶泡", steam_time, lambda: self._step_steam_milk(steam_time)))
        
        # 完成
        steps.append(BrewStep("制作完成", 1.0, self._step_finish))
        
        job.steps = steps
    
    def _brew_process(self, job: BrewJob):
        """制作流程"""
        try:
            job.status = BrewStatus.PREPARING
            job.start_time = datetime.now()
            
            self._notify_status_change({
                'event': 'job_started',
                'job_id': job.job_id,
                'coffee_type': job.coffee_type.value
            })
            
            total_duration = sum(step.duration for step in job.steps)
            elapsed_time = 0.0
            
            for i, step in enumerate(job.steps):
                if self.stop_event.is_set():
                    job.status = BrewStatus.CANCELLED
                    break
                
                job.current_step = i
                job.progress = elapsed_time / total_duration * 100
                
                logger.info(f"执行步骤: {step.name}")
                self._notify_status_change({
                    'event': 'step_started',
                    'job_id': job.job_id,
                    'step': step.name,
                    'progress': job.progress
                })
                
                step.start_time = datetime.now()
                
                # 执行步骤动作
                if step.action:
                    try:
                        step.action()
                    except Exception as e:
                        logger.error(f"步骤执行错误 {step.name}: {e}")
                        job.status = BrewStatus.ERROR
                        job.error_message = str(e)
                        break
                
                # 等待步骤完成
                step_elapsed = 0.0
                while step_elapsed < step.duration and not self.stop_event.is_set():
                    time.sleep(0.5)
                    step_elapsed += 0.5
                    elapsed_time += 0.5
                    job.progress = min(100.0, elapsed_time / total_duration * 100)
                
                step.completed = True
                
                self._notify_status_change({
                    'event': 'step_completed',
                    'job_id': job.job_id,
                    'step': step.name,
                    'progress': job.progress
                })
            
            # 设置最终状态
            if job.status != BrewStatus.CANCELLED and job.status != BrewStatus.ERROR:
                job.status = BrewStatus.FINISHED
                job.progress = 100.0
            
            job.end_time = datetime.now()
            
            # 停止所有组件
            self._stop_all_components()
            
            # 添加到历史记录
            self.job_history.append(job)
            
            # 通知完成
            self._notify_status_change({
                'event': 'job_completed',
                'job_id': job.job_id,
                'status': job.status.value,
                'duration': (job.end_time - job.start_time).total_seconds()
            })
            
            logger.info(f"制作任务完成: {job.job_id}, 状态: {job.status.value}")
            
        except Exception as e:
            logger.error(f"制作流程错误: {e}")
            job.status = BrewStatus.ERROR
            job.error_message = str(e)
            job.end_time = datetime.now()
    
    def _step_prepare(self):
        """准备步骤"""
        # 检查硬件状态
        temperature = self.hardware.get_temperature()
        water_level = self.hardware.get_water_level()
        
        if water_level < 10:
            raise Exception("水位过低，请加水")
        
        logger.info(f"准备完成，当前温度: {temperature}°C，水位: {water_level}%")
    
    def _step_grind(self, duration: float):
        """研磨步骤"""
        self.hardware.start_grinder(duration)
    
    def _step_heat_water(self):
        """加热步骤"""
        self.hardware.start_heater()
        
        # 等待温度达到目标
        target_temp = 85.0
        timeout = 30.0
        start_time = time.time()
        
        while time.time() - start_time < timeout and not self.stop_event.is_set():
            current_temp = self.hardware.get_temperature()
            if current_temp >= target_temp:
                break
            time.sleep(1.0)
    
    def _step_brew_coffee(self, duration: float, recipe: Dict[str, Any]):
        """萃取步骤"""
        # 启动水泵
        self.hardware.start_water_pump(duration)
    
    def _step_steam_milk(self, duration: float):
        """蒸汽步骤"""
        self.hardware.start_steam(duration)
    
    def _step_finish(self):
        """完成步骤"""
        # 停止加热器
        self.hardware.stop_heater()
        logger.info("咖啡制作完成")
    
    def _stop_all_components(self):
        """停止所有硬件组件"""
        try:
            self.hardware.stop_heater()
            # 其他组件会自动停止（基于定时器）
        except Exception as e:
            logger.error(f"停止组件时出错: {e}")

def create_coffee_maker(hardware: HardwareInterface, config: Dict[str, Any]) -> CoffeeMaker:
    """创建咖啡机控制器"""
    recipes = config.get('coffee', {}).get('default_recipes', {})
    return CoffeeMaker(hardware, recipes)