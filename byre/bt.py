#  Copyright (C) 2023 Yesh
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import os.path
import typing
from urllib.parse import urlparse

import qbittorrentapi

from byre import utils
from byre.data import LocalTorrent, TorrentInfo

_logger = logging.getLogger("byre.bt")
_debug, _info, _warning, _fatal = _logger.debug, _logger.info, _logger.warning, _logger.fatal


class BtClient:
    """对 qBittorrent 客户端的各种操作进行封装。"""

    def __init__(self, url: str, download_dir: str):
        info = urlparse(url)
        scheme = info.scheme or "http"
        self._dir = os.path.realpath(download_dir)
        self.client = qbittorrentapi.Client(
            host=f"{scheme}://{info.hostname}",
            port=info.port,
            username=info.username,
            password=info.password,
        )
        self.client.auth_log_in()
        _debug("qBittorrent 信息：软件版本 %s，API 版本 %s", self.client.app.version, self.client.app.web_api_version)
        if self.client.app.version < "v4.5.2":
            raise ConnectionError("请升级到更新的 qBittorrent 版本")

    def init_categories(self, categories: typing.Iterable[str]):
        """创建类别并设置下载目录，不会更改现有类别的设置。"""
        existing = set(self.client.torrents_categories().keys())
        for category in categories:
            if category in existing:
                _debug("类别“%s”已存在，跳过创建", category)
                continue
            download_dir = os.path.join(self._dir, category)
            os.makedirs(download_dir, exist_ok=True)
            _debug("正在创建类别“%s”", category)
            self.client.torrents_create_category(
                category,
                torrent_dir=download_dir,
            )

    def remove_categories(self, categories: typing.Iterable[str]):
        """删除类别。"""
        existing = set(self.client.torrents_categories().keys())
        removable = existing & set(categories)
        _debug("计划删除类别 %s，最终应删除 %s", categories, removable)
        self.client.torrents_remove_categories(removable)

    def init_tags(self, reset=False):
        """创建（或删除）“byr”标签。"""
        if "byr" not in self.client.torrents_tags():
            if not reset:
                self.client.torrents_create_tags(["byr"])
                _debug("创建了“byr”标签")
                return
        elif reset:
            self.client.torrents_delete_tags(["byr"])
            _debug("删除了“byr”标签")
            return
        _debug("无需创建/删除标签")

    def add_torrent(self, torrent: bytes, info: TorrentInfo, paused=False):
        """添加种子并设置对应的类别和标签。"""
        title = f"[byr-{info.seed_id}]{info.title}"
        _info("正在添加种子“%s”", title)
        self.client.torrents_add(
            torrent_files=torrent,
            save_path=self._get_download_dir(info),
            category=info.category,
            is_skip_checking=False,
            is_paused=paused,
            rename=title,
            tags=["byr"],
        )

    def remove_torrent(self, torrent: LocalTorrent):
        """删除种子并删除对应的文件。"""
        _info("正在删除种子“%s”", torrent.torrent.name)
        self.client.torrents_delete(delete_files=True, torrent_hashes=[torrent.torrent.hash])

    def list_torrents(self, remote_torrents: list[TorrentInfo]):
        """列出所有本地带有“byr”标签且命名符合要求的种子。"""
        remote_mapping = dict((t.seed_id, t) for t in remote_torrents)
        torrents = []
        for torrent in self.client.torrents_info(tag="byr"):
            name: str = torrent["name"]
            if name.startswith("[byr-"):
                seed_id = utils.int_or(name[5:name.index("]")])
                if seed_id != 0:
                    torrents.append(LocalTorrent(torrent, seed_id, remote_mapping.get(seed_id, None)))
                    continue
            _warning("种子命名不符合要求：%s", name)
        return torrents

    def _get_download_dir(self, torrent: TorrentInfo):
        """下载目录，由种子分类及二级分类决定。"""
        return (os.path.join(self._dir, torrent.category, torrent.second_category)
                if torrent.second_category else os.path.join(self._dir, torrent.category))
