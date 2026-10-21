#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导出路由模块
@File    :  data_export.py
@Time    :  2026/08/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  hdmap 提取 + ros2 bag 录制 REST API；仅做参数校验、调用 service、返回响应
            符合 README「解耦开发规范」第 2 条：routers/ 不含业务逻辑
"""

from typing import Optional
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from deps import require_permission
from services.data_export_service import DataExportService
from database import db
from logger import logger

router = APIRouter()


class HdmapExtractRequest(BaseModel):
    container_name: str
    sn: str
    target_user: Optional[str] = None


class BagRecordRequest(BaseModel):
    container_name: str
    target_user: Optional[str] = None


class BagStopRequest(BaseModel):
    container_name: str
    target_user: Optional[str] = None


class BagDeleteRequest(BaseModel):
    filenames: list
    target_user: Optional[str] = None


@router.get("/api/data-export/hdmap/sn-list")
async def list_hdmap_sn(
    container_name: str,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        logger.info(f"列出SN列表: container={container_name}, user={current_user.get('username')}")
        sn_list = DataExportService._list_sn_dirs(container_name)
        return {"success": True, "sn_list": sn_list}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"列出SN列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/data-export/hdmap/extract")
async def extract_hdmap(
    data: HdmapExtractRequest,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        result = DataExportService.extract_hdmap(
            container_name=data.container_name,
            sn=data.sn,
            current_user=current_user,
            target_user=data.target_user
        )
        target = data.target_user or current_user.get("username", "")
        db.add_audit_log(current_user["username"], "extract_hdmap",
                         f"container={data.container_name} sn={data.sn} target={target}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"提取地图异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/data-export/bag/start")
async def start_bag_record(
    data: BagRecordRequest,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        result = DataExportService.start_bag_record(
            container_name=data.container_name,
            current_user=current_user,
            target_user=data.target_user
        )
        target = data.target_user or current_user.get("username", "")
        db.add_audit_log(current_user["username"], "start_bag_record",
                         f"container={data.container_name} target={target}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"启动录制异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/data-export/bag/stop")
async def stop_bag_record(
    data: BagStopRequest,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        result = DataExportService.stop_bag_record(
            container_name=data.container_name,
            current_user=current_user,
            target_user=data.target_user
        )
        target = data.target_user or current_user.get("username", "")
        db.add_audit_log(current_user["username"], "stop_bag_record",
                         f"container={data.container_name} target={target}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"停止录制异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/data-export/bag/status")
async def get_bag_status(
    container_name: str,
    current_user: dict = Depends(require_permission('data-export'))
):
    logger.debug(f"查询bag状态: container={container_name}, user={current_user.get('username')}")
    return DataExportService.get_bag_status(container_name)


@router.get("/api/data-export/bag/list")
async def list_bag_files(
    container_name: Optional[str] = None,
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        logger.debug(f"列出bag文件: container={container_name}, user={current_user.get('username')}")
        return DataExportService.list_bag_files(current_user, target_user, container_name)
    except Exception as e:
        logger.error(f"列出bag文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/api/data-export/bag/delete", methods=["POST", "DELETE"])
async def delete_bag_files(
    request: Request,
    filenames_param: Optional[str] = None,
    current_user: dict = Depends(require_permission('data-export'))
):
    try:
        filenames = []
        target_user = None

        if request.method == "POST":
            data = await request.json()
            filenames = data.get("filenames", [])
            target_user = data.get("target_user")
        else:
            if filenames_param:
                import json as _json
                try:
                    filenames = _json.loads(filenames_param)
                except Exception:
                    filenames = [f.strip() for f in filenames_param.split(",") if f.strip()]
            if not filenames:
                try:
                    data = await request.json()
                    filenames = data.get("filenames", [])
                    target_user = data.get("target_user")
                except Exception:
                    pass

        if not filenames:
            raise HTTPException(status_code=400, detail="未指定要删除的文件")
        result = DataExportService.delete_bag_files(
            filenames=filenames,
            current_user=current_user,
            target_user=target_user
        )
        target = target_user or current_user.get("username", "")
        db.add_audit_log(current_user["username"], "delete_bag_files",
                         f"files={filenames} target={target}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除bag文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/data-export/bag/download")
async def download_bag_file(
    file: str,
    target_user: Optional[str] = None,
    current_user: dict = Depends(require_permission('data-export'))
):
    if not file or os.sep in file or '/' in file or '..' in file:
        raise HTTPException(status_code=400, detail="非法文件名")

    bag_storage = DataExportService._get_bag_storage(current_user, target_user)
    full_path = os.path.normpath(os.path.join(bag_storage, file))

    if not full_path.startswith(os.path.normpath(bag_storage)):
        raise HTTPException(status_code=400, detail="非法路径访问")

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    logger.info(f"下载文件: {full_path}, user={current_user.get('username')}")
    return FileResponse(full_path, filename=os.path.basename(full_path))
