"""
抖音自动化系统主程序入口
"""
import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.browser_manager import browser_manager
from core.task_scheduler import TaskScheduler
from utils.data_storage import data_storage
from utils.strings import split_list  # 新增导入

class DouyinAutomationSystem:
    """抖音自动化系统主类"""
    
    def __init__(self):
        self.task_scheduler = TaskScheduler()
        self.system_running = False
    
    async def initialize(self):
        """初始化系统"""
        print("🎯 初始化抖音自动化系统...")
        
        # 初始化任务调度器
        await self.task_scheduler.initialize()
        
        # 设置事件回调
        self.task_scheduler.add_event_callback(self._handle_system_event)
        
        # 初始化数据库
        data_storage.init_database()
        
        self.system_running = True
        print("✅ 系统初始化完成")
    
    async def start_service(self, service_name: str, **kwargs) -> bool:
        """启动服务"""
        if not self.system_running:
            print("❌ 系统未初始化")
            return False
        
        return await self.task_scheduler.start_service(service_name, **kwargs)
    
    async def stop_service(self, service_name: str):
        """停止服务"""
        await self.task_scheduler.stop_service(service_name)
    
    async def stop_all_services(self):
        """停止所有服务"""
        await self.task_scheduler.stop_all_services()
    
    async def start_browser(self) -> bool:
        """启动浏览器"""
        return await browser_manager.start_browser(headless=False)
    
    async def close(self):
        """关闭系统"""
        print("🔴 正在关闭系统...")
        
        await self.stop_all_services()
        await browser_manager.close()
        
        self.system_running = False
        print("✅ 系统已关闭")
    
    async def _handle_system_event(self, event):
        """处理系统事件"""
        event_type = event.get("type")
        service_name = event.get("service", "Unknown")
        data = event.get("data", "")
        
        if event_type == "error":
            print(f"❌ [{service_name}] 错误: {data}")
        elif event_type == "operation":
            print(f"🔧 [{service_name}] {data}")
        elif event_type == "started":
            print(f"🚀 [{service_name}] 服务已启动")
        elif event_type == "finished":
            print(f"🏁 [{service_name}] 服务已完成: {data}")
        elif event_type == "warning":
            print(f"⚠️ [{service_name}] 警告: {data}")
        else:
            print(f"📢 [{service_name}] {event_type}: {data}")

# 全局系统实例
_system_instance = None

async def get_system():
    """获取系统实例（单例）"""
    global _system_instance
    if _system_instance is None:
        _system_instance = DouyinAutomationSystem()
        await _system_instance.initialize()
    return _system_instance

async def main():
    """主函数 - 命令行界面"""
    system = await get_system()
    
    print("🎯 抖音自动化系统")
    print("=" * 50)
    
    try:
        while True:
            print("\n请选择操作:")
            print("1. 启动浏览器")
            print("2. 开始随机点赞")
            print("3. 阶段一：视频采集")
            print("4. 阶段二：用户采集")
            print("5. 开始私信")
            print("6. 停止所有服务")
            print("7. 系统状态")
            print("8. 退出系统")
            
            choice = input("\n请输入选项 (1-8): ").strip()
            
            if choice == "1":
                if await system.start_browser():
                    print("✅ 浏览器启动成功")
                else:
                    print("❌ 浏览器启动失败")
            
            elif choice == "2":
                duration = input("请输入运行时间(分钟，默认10): ").strip()
                duration = int(duration) if duration.isdigit() else 10
                
                if await system.start_service("RandomLikeService", duration_minutes=duration):
                    print("✅ 随机点赞服务已启动")
                else:
                    print("❌ 随机点赞服务启动失败")
            
            elif choice == "3":
                keywords = input("请输入内容关键词(空格分隔): ").strip()
                sort_type = input("排序方式(最新/最热，默认最新): ").strip() or "最新"
                videos_per_keyword = input("每个关键词处理视频数(默认5): ").strip()
                videos_per_keyword = int(videos_per_keyword) if videos_per_keyword.isdigit() else 5
                duration = input("运行时间(分钟，默认10): ").strip()
                duration = int(duration) if duration.isdigit() else 10
                
                keyword_list = split_list(keywords)  # 使用统一的字符串分割函数
                
                if not keyword_list:
                    print("❌ 请输入内容关键词")
                    continue
                
                #await system.start_browser()
                
                if await system.start_service(
                    "CustomerAcquisitionService",
                    keywords=keyword_list,
                    sort_type=sort_type,
                    videos_per_keyword=videos_per_keyword,
                    duration_minutes=duration
                ):
                    print("✅ 阶段一视频采集服务已启动")
                else:
                    print("❌ 阶段一视频采集服务启动失败")
            
            elif choice == "4":
                video_urls = input("请输入视频链接(空格分隔): ").strip()
                user_comment_keywords = input("请输入用户评论关键词(空格分隔): ").strip()
                ip_keywords = input("请输入IP归属地关键词(空格分隔，留空为任意): ").strip()
                duration = input("运行时间(分钟，默认10): ").strip()
                duration = int(duration) if duration.isdigit() else 10
                
                video_list = split_list(video_urls)  # 使用统一的字符串分割函数
                user_comment_list = split_list(user_comment_keywords)  # 使用统一的字符串分割函数
                ip_list = split_list(ip_keywords)  # 使用统一的字符串分割函数
                
                if not video_list:
                    print("❌ 请选择视频")
                    continue
                    
                if not user_comment_list:
                    print("❌ 请输入用户评论关键词")
                    continue
                
                #await system.start_browser()
                
                if await system.start_service(
                    "CustomerAcquisitionService",
                    videos=video_list,
                    user_comment_keywords=user_comment_list,
                    ip_keywords=ip_list,
                    duration_minutes=duration
                ):
                    print("✅ 阶段二用户采集服务已启动")
                else:
                    print("❌ 阶段二用户采集服务启动失败")
            
            elif choice == "5":
                message_template = input("请输入私信模板(默认: 您好，看到您的评论，很高兴认识您！): ").strip()
                if not message_template:
                    message_template = "您好，看到您的评论，很高兴认识您！"
                
                duration = input("运行时间(分钟，默认10): ").strip()
                duration = int(duration) if duration.isdigit() else 10
                
                if await system.start_service(
                    "PrivateMessageService",
                    message_template=message_template,
                    duration_minutes=duration
                ):
                    print("✅ 私信服务已启动")
                else:
                    print("❌ 私信服务启动失败")
            
            elif choice == "6":
                await system.stop_all_services()
                print("🛑 所有服务已停止")
            
            elif choice == "7":
                status = await system.task_scheduler.get_all_services_status()
                browser_status = "运行中" if browser_manager.is_running else "未运行"
                
                print(f"\n📊 系统状态:")
                print(f"🖥️  浏览器: {browser_status}")
                print(f"🛠️  服务状态:")
                
                for service_name, service_status in status.items():
                    status_text = "运行中" if service_status.get('running', False) else "未运行"
                    print(f"  - {service_name}: {status_text}")
            
            elif choice == "8":
                break
            
            else:
                print("❌ 无效选择，请重新输入")
    
    except KeyboardInterrupt:
        print("\n🛑 用户中断")
    except Exception as e:
        print(f"❌ 系统错误: {e}")
    finally:
        await system.close()
        print("🔴 系统已关闭")

if __name__ == "__main__":
    # 运行主程序
    asyncio.run(main())