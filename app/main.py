import os
import asyncio
from pathlib import Path
import datetime
from datetime import timezone

from app.services.buy_service import pay_for_products
from app.services.delivery_service import do_delivery
from app.services.transactions_service import make_transactions_report

from db import init_db, get_db
from oltp_sync import authorize_shop, authorize_employee, authorize_terminal, get_id_available_terminals
from oltp_sync import sync_categories, sync_products
from app import Shop, Employee

time_step = 0.01
minutes_step = 5
shop: Shop = None
admin: Employee = None
courier: Employee = None

SHOP_ID = os.getenv('SHOP_ID')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')
COURIER_EMAIL = os.getenv('COURIER_EMAIL')
CASHIER_1_EMAIL = os.getenv('CASHIER_1_EMAIL')
CASHIER_2_EMAIL = os.getenv('CASHIER_2_EMAIL')
CASHIER_3_EMAIL = os.getenv('CASHIER_3_EMAIL')

_real_datetime = datetime.datetime

class PatchedDateTime(datetime.datetime):
    _fake_now = _real_datetime(2025, 6, 1, 8, 0)

    @classmethod
    def now(cls, tz=None):
        return cls._fake_now

    @classmethod
    def add_minutes(cls, minutes):
        cls._fake_now += datetime.timedelta(minutes=minutes)
        
datetime.datetime = PatchedDateTime

async def main():
    asyncio.create_task(start_time())
    # 90 days
    for _ in range(1, 61):  
        await start_work_shift()

async def start_work_shift():    
    global shop, admin, courier, working_time
    
    while datetime.datetime.now().hour < 9:
        await asyncio.sleep(time_step)
    
    init_db()
    shop = authorize_shop(SHOP_ID, 'password')
    if shop:
        print(f"Shop {shop.shop_id} is authorized.")
    else:
        print(f"Authorization {shop.shop_id} failed.")
        return
    
    admin = authorize_employee(ADMIN_EMAIL, 'password')
    if admin:
        print(f"Admin {admin.first_name} is authorized.")
    else:
        print(f"Authorization {admin.first_name} failed.")
        return
    
    courier = authorize_employee(COURIER_EMAIL, 'password')
    if courier:
        print(f"Courier {courier.first_name} is authorized.")
    else:
        print(f"Authorization {courier.first_name} failed.")
        return
    
    terminals = get_id_available_terminals(shop.shop_id)
    if terminals:
        for terminal in terminals:
            if not authorize_terminal(shop.shop_id, terminal, 'password'):
                print(f"Authorization terminal {terminal} failed.")
                return
            print(f"Terminal {terminal} is authorized.")
    
    sync()
    print(f'Work is started {datetime.datetime.now()}')
    
    task_delivery = asyncio.create_task(start_delivery_process())
    task1 = asyncio.create_task(start_cashier_working(terminals[0], CASHIER_1_EMAIL, 'password'))
    task2 = asyncio.create_task(start_cashier_working(terminals[1], CASHIER_2_EMAIL, 'password'))
    task3 = asyncio.create_task(start_cashier_working(terminals[2], CASHIER_3_EMAIL, 'password'))
    
    await asyncio.gather(task_delivery, task1, task2, task3)
    print(f'Work is ended {datetime.datetime.now()}')
    datetime.datetime.add_minutes(11 * 60 / minutes_step)
    db = next(get_db())
    try:
        make_transactions_report(db, shop, admin)
    finally:
        db.close()
    
def sync():
    path = Path(f"sync_time_{shop.shop_id}")
    if path.exists():
        sync_time = path.read_text()
    else:
        sync_time = datetime.datetime.min.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
        
    db = next(get_db())
    try:
        sync_categories(db, sync_time)
        sync_products(db, shop.shop_id, sync_time)
        print("Synchronized successfully.")
    finally:
        db.close()
        path.write_text(datetime.datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
           
async def start_time():
    while True:
        await asyncio.sleep(time_step)
        datetime.datetime.add_minutes(minutes_step)
        
async def start_delivery_process():
    while 9 <= datetime.datetime.now().hour < 21:
        now = datetime.datetime.now()
        if now.hour == 10 or now.hour == 18:
            db = next(get_db())
            try:
                do_delivery(db, shop, admin, courier)
            finally:
                db.close()
            await asyncio.sleep(60 / minutes_step * time_step )
        await asyncio.sleep(time_step)
    
async def start_cashier_working(terminal_id, email: str, password: str):
    employee = authorize_employee(email, password)
    if employee:
        print(f"Employee {employee.first_name} is authorized. Terminal ID: {terminal_id}")
    else:
        print(f"Authorization {shop.shop_id} failed.")
        return
    
    while 9 <= datetime.datetime.now().hour < 21:
        db = next(get_db())
        try:
            pay_for_products(db, terminal_id, employee)
        finally:
            db.close()
        await asyncio.sleep(time_step)
        
    
if __name__ == "__main__":
    asyncio.run(main())
