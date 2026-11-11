from shared.logger import get_logger
from services.POS_manager import pos_manager
from services.Task_manager import task_service
from services.Robot_manager import robot_service
from core.config import settings
import asyncio
import time
import uuid
import re
from fastapi import HTTPException
import httpx

logger = get_logger("logic_service")
ics_url = f"http://{settings.ics_host}:7000"

async def process_auto(data):
    type_point = data.get("logic_type") 

    match type_point:
        case 1: 
            await handle_logic_1(data)
        case 2:
            await handle_logic_2(data)
        case 2.1:
            await handle_logic_2_1(data)
        case 2.2:
            await handle_logic_2_2(data)
        case _:
            pass

async def add_task(payload):
    return await pos_manager.send_robot_task(payload, ics_url)

async def request_RCS(data, target_robot = None):
    order_id = f"4-{time.strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:4]}"
    payload = None

    if target_robot is not None:
        logger.info("----Sending Returns in Zone AE----")
        payload = {
                "modelProcessCode": "Tra_XT_AE", 
                "fromSystem": "Thadosoft", 
                "orderId": order_id,  
                "priority": 4,
                "taskOrderDetail": [ 
                    {    
                        "taskPath": f"{data[0]},{data[1]}",
                        "assignRobotIds": f"{target_robot}"
                    } 
                ] 
            }

    elif len(data) == 2:
        logger.info("----Sending RCS SINGLE AE----")
        payload = {
                "modelProcessCode": "Cap_PT_AE", 
                "fromSystem": "Thadosoft", 
                "orderId": order_id,  
                "taskOrderDetail": [ 
                    {    
                        "taskPath": f"{data[0]},{data[1]}"
                    } 
                ] 
            }

    elif len(data) == 4:
        logger.info("----Sending RCS DUAL AE----")
        payload = {
                "modelProcessCode": "Cap_tra_PT_AE", 
                "fromSystem": "Thadosoft", 
                "orderId": order_id,  
                "taskOrderDetail": [ 
                    {    
                        "taskPath": f"{data[0]},{data[1]}"
                    }, 
                    {    
                        "taskPath": f"{data[2]},{data[3]}"
                    } 
                ] 
            } 

    else:
        return None

    if payload:
        track_data = {
            "position": data[0]
        }
        #Handle RCS response
        await task_service.track_for_task(order_id, track_data)
        if not await add_task(payload):
            task_service.tracking_task.pop(order_id, None)
            return False
        # Reservation was acquired before HTTP; do not re-lock after an early callback.
        if target_robot is not None:
            for zone_robots in robot_service.robot_in_zones.values():
                if target_robot in zone_robots:
                    zone_robots.remove(target_robot)
    

async def handle_logic_1(data):
    matching = data.get("matching", [])
    if len(matching) < 4:
        logger.warning("Not enough 4 points data matching")
        return None

    point_to_check = matching[1:3]
    states = await pos_manager.get_state(point_to_check)

    if not states:
        return None

    s1, s2 = states[0], states[1]

    if s1 == "trong" and s2 == "hang":
        data = [matching[0], matching[1], matching[2], matching[3]]
        await request_RCS(data)

    elif s1 == "trong":
        data = [matching[0], matching[1]]
        await request_RCS(data)


async def handle_logic_2(data):
    matching = data.get("matching", [])

    point_list = matching[1:2]
    states = await pos_manager.get_state(point_list)

    if not states:
        return None

    s1 = states[0]

    if s1 == "trong":
        data = [matching[0], matching[1]]
        await request_RCS(data)

async def handle_logic_2_1(data):
    matching = data.get("matching", [])
    logger.info(f"Execute logic 2.1")

    point_to_check = matching[1:]
    states = await pos_manager.get_state(point_to_check)

    if not states:
        return None

    for i, state in enumerate(states):
        if state == "trong":
            data = [matching[0], matching[i+1]]
            await request_RCS(data)

            break

async def handle_logic_2_2(data):
    matching = data.get("matching", [])
    point_to_check = matching[1:2]
    states = await pos_manager.get_state(point_to_check)

    if not states:
        return None

    s1 = states[0]

    if s1 == "trong":
        zone = data.get("zone", [])
        robots_in_zone = robot_service.robot_in_zones.get(zone)

        if not robots_in_zone:
            return

        target_robot = robots_in_zone[0]

        data = [matching[0], matching[1]]
        await request_RCS(data, target_robot)



