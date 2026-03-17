"""
utils/vpn.py
~~~~~~~~~~~~
Provider-agnostic VPN manager for NovaPlay.

This module does not ship a VPN network. It manages local VPN sessions using
provider-issued WireGuard/OpenVPN configs and a host catalog. To get a
"global, high-speed" experience, populate the catalog with real endpoints
from your VPN provider.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class VPNProtocol(str, Enum):
	WIREGUARD = "wireguard"
	OPENVPN = "openvpn"


class VPNError(RuntimeError):
	"""Raised when a VPN operation fails."""


@dataclass(frozen=True)
class VPNHost:
	"""A single provider endpoint + local config needed to connect."""

	host_id: str
	provider: str
	country: str
	city: str
	hostname: str
	protocol: VPNProtocol
	port: int
	config_path: str
	tags: set[str] = field(default_factory=set)

	@property
	def region_key(self) -> str:
		return f"{self.country.lower()}:{self.city.lower()}"


@dataclass
class VPNStatus:
	connected: bool = False
	active_host: Optional[VPNHost] = None
	connected_since: float = 0.0
	latency_ms: Optional[float] = None


@dataclass
class VPNCatalog:
	hosts: list[VPNHost] = field(default_factory=list)

	def by_region(self, country: str, city: Optional[str] = None) -> list[VPNHost]:
		country_l = country.lower()
		city_l = city.lower() if city else None
		result: list[VPNHost] = []
		for host in self.hosts:
			if host.country.lower() != country_l:
				continue
			if city_l is not None and host.city.lower() != city_l:
				continue
			result.append(host)
		return result

	def by_protocol(self, protocol: VPNProtocol) -> list[VPNHost]:
		return [h for h in self.hosts if h.protocol == protocol]


def _default_catalog_path() -> Path:
	return Path.home() / ".novaplay" / "vpn_hosts.json"


def _default_runtime_dir() -> Path:
	return Path.home() / ".novaplay" / "vpn_runtime"


def _template_catalog() -> dict:
	"""
	Template containing many regions; replace hostnames/config paths with your
	provider exports (for example, Proton/OpenVPN/WireGuard profiles).
	"""
	return {
		"hosts": [
			{
				"host_id": "us-nyc-wg-1",
				"provider": "your-provider",
				"country": "US",
				"city": "New York",
				"hostname": "us-nyc-1.example-vpn.net",
				"protocol": "wireguard",
				"port": 51820,
				"config_path": "~/vpn-configs/us-nyc-wg-1.conf",
				"tags": ["streaming", "high-speed"],
			},
			{
				"host_id": "us-sfo-ovpn-1",
				"provider": "your-provider",
				"country": "US",
				"city": "San Francisco",
				"hostname": "us-sfo-1.example-vpn.net",
				"protocol": "openvpn",
				"port": 1194,
				"config_path": "~/vpn-configs/us-sfo-ovpn-1.ovpn",
				"tags": ["high-speed"],
			},
			{
				"host_id": "de-fra-wg-1",
				"provider": "your-provider",
				"country": "DE",
				"city": "Frankfurt",
				"hostname": "de-fra-1.example-vpn.net",
				"protocol": "wireguard",
				"port": 51820,
				"config_path": "~/vpn-configs/de-fra-wg-1.conf",
				"tags": ["core"],
			},
			{
				"host_id": "nl-ams-wg-1",
				"provider": "your-provider",
				"country": "NL",
				"city": "Amsterdam",
				"hostname": "nl-ams-1.example-vpn.net",
				"protocol": "wireguard",
				"port": 51820,
				"config_path": "~/vpn-configs/nl-ams-wg-1.conf",
				"tags": ["core"],
			},
			{
				"host_id": "uk-lon-ovpn-1",
				"provider": "your-provider",
				"country": "UK",
				"city": "London",
				"hostname": "uk-lon-1.example-vpn.net",
				"protocol": "openvpn",
				"port": 1194,
				"config_path": "~/vpn-configs/uk-lon-ovpn-1.ovpn",
				"tags": ["core"],
			},
			{
				"host_id": "sg-sin-wg-1",
				"provider": "your-provider",
				"country": "SG",
				"city": "Singapore",
				"hostname": "sg-sin-1.example-vpn.net",
				"protocol": "wireguard",
				"port": 51820,
				"config_path": "~/vpn-configs/sg-sin-wg-1.conf",
				"tags": ["asia", "high-speed"],
			},
			{
				"host_id": "jp-tyo-wg-1",
				"provider": "your-provider",
				"country": "JP",
				"city": "Tokyo",
				"hostname": "jp-tyo-1.example-vpn.net",
				"protocol": "wireguard",
				"port": 51820,
				"config_path": "~/vpn-configs/jp-tyo-wg-1.conf",
				"tags": ["asia"],
			},
			{
				"host_id": "in-mum-ovpn-1",
				"provider": "your-provider",
				"country": "IN",
				"city": "Mumbai",
				"hostname": "in-mum-1.example-vpn.net",
				"protocol": "openvpn",
				"port": 1194,
				"config_path": "~/vpn-configs/in-mum-ovpn-1.ovpn",
				"tags": ["india", "low-latency"],
			},
		]
	}


def ensure_catalog_file(path: Optional[Path] = None) -> Path:
	path = path or _default_catalog_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	if not path.exists():
		path.write_text(json.dumps(_template_catalog(), indent=2), encoding="utf-8")
	return path


def load_catalog(path: Optional[Path] = None) -> VPNCatalog:
	path = ensure_catalog_file(path)
	raw = json.loads(path.read_text(encoding="utf-8"))
	hosts: list[VPNHost] = []
	for item in raw.get("hosts", []):
		hosts.append(
			VPNHost(
				host_id=str(item["host_id"]),
				provider=str(item.get("provider", "unknown")),
				country=str(item["country"]),
				city=str(item["city"]),
				hostname=str(item["hostname"]),
				protocol=VPNProtocol(str(item["protocol"]).lower()),
				port=int(item["port"]),
				config_path=str(item["config_path"]),
				tags={str(t).lower() for t in item.get("tags", [])},
			)
		)
	return VPNCatalog(hosts=hosts)


def _expand_path(path_str: str) -> str:
	return str(Path(path_str).expanduser().resolve())


def _measure_latency_ms(hostname: str, port: int, timeout: float = 1.2) -> Optional[float]:
	start = time.perf_counter()
	try:
		with socket.create_connection((hostname, port), timeout=timeout):
			pass
	except OSError:
		return None
	return (time.perf_counter() - start) * 1000.0


class VPNManager:
	"""
	Handles selecting and connecting the best VPN endpoint from a catalog.

	- Uses WireGuard/OpenVPN configs exported by your provider.
	- Chooses low-latency hosts for better speed.
	- Supports graceful disconnect and health probing.
	"""

	def __init__(
		self,
		catalog_path: Optional[Path] = None,
		*,
		runtime_dir: Optional[Path] = None,
		command_timeout_s: int = 25,
		runner: Optional[Callable[[list[str]], subprocess.CompletedProcess]] = None,
	) -> None:
		self.catalog_path = catalog_path or _default_catalog_path()
		self.runtime_dir = runtime_dir or _default_runtime_dir()
		self.runtime_dir.mkdir(parents=True, exist_ok=True)
		self.command_timeout_s = command_timeout_s
		self._runner = runner
		self._catalog = load_catalog(self.catalog_path)
		self._status = VPNStatus()
		self._lock = threading.RLock()

		self._openvpn_pid_file = self.runtime_dir / "openvpn.pid"

	@property
	def status(self) -> VPNStatus:
		with self._lock:
			return VPNStatus(
				connected=self._status.connected,
				active_host=self._status.active_host,
				connected_since=self._status.connected_since,
				latency_ms=self._status.latency_ms,
			)

	@property
	def catalog(self) -> VPNCatalog:
		return self._catalog

	def reload_catalog(self) -> None:
		self._catalog = load_catalog(self.catalog_path)

	def available_regions(self) -> list[str]:
		values = {f"{h.country}-{h.city}" for h in self._catalog.hosts}
		return sorted(values)

	def rank_hosts(
		self,
		hosts: list[VPNHost],
		*,
		probes: int = 12,
		timeout_s: float = 1.2,
	) -> list[tuple[VPNHost, float]]:
		if not hosts:
			return []

		sampled = hosts[:probes]
		ranked: list[tuple[VPNHost, float]] = []
		with ThreadPoolExecutor(max_workers=min(8, len(sampled))) as pool:
			future_to_host = {
				pool.submit(_measure_latency_ms, h.hostname, h.port, timeout_s): h
				for h in sampled
			}
			for future in as_completed(future_to_host):
				host = future_to_host[future]
				latency = future.result()
				if latency is not None:
					ranked.append((host, latency))

		ranked.sort(key=lambda item: item[1])
		return ranked

	def pick_best_host(
		self,
		*,
		country: Optional[str] = None,
		city: Optional[str] = None,
		protocol: Optional[VPNProtocol] = None,
		tags_any: Optional[set[str]] = None,
	) -> tuple[VPNHost, float]:
		candidates = list(self._catalog.hosts)
		if country:
			candidates = [h for h in candidates if h.country.lower() == country.lower()]
		if city:
			candidates = [h for h in candidates if h.city.lower() == city.lower()]
		if protocol:
			candidates = [h for h in candidates if h.protocol == protocol]
		if tags_any:
			tags_any_l = {t.lower() for t in tags_any}
			candidates = [h for h in candidates if h.tags & tags_any_l]

		if not candidates:
			raise VPNError("No VPN hosts match the requested filters")

		ranked = self.rank_hosts(candidates)
		if not ranked:
			raise VPNError(
				"No reachable VPN host found. Check DNS/network and provider endpoints"
			)
		return ranked[0]

	def connect(
		self,
		*,
		country: Optional[str] = None,
		city: Optional[str] = None,
		protocol: Optional[VPNProtocol] = None,
		tags_any: Optional[set[str]] = None,
	) -> VPNStatus:
		"""
		Connects to the best available host for the given filters.
		Requires sudo privileges for tunnel setup.
		"""
		with self._lock:
			if self._status.connected:
				raise VPNError("VPN is already connected. Disconnect first.")

			host, latency = self.pick_best_host(
				country=country,
				city=city,
				protocol=protocol,
				tags_any=tags_any,
			)
			self._connect_host(host)
			self._status.connected = True
			self._status.active_host = host
			self._status.connected_since = time.time()
			self._status.latency_ms = latency
			return self.status

	def connect_host_id(self, host_id: str) -> VPNStatus:
		with self._lock:
			if self._status.connected:
				raise VPNError("VPN is already connected. Disconnect first.")

			host = next((h for h in self._catalog.hosts if h.host_id == host_id), None)
			if host is None:
				raise VPNError(f"Unknown host_id: {host_id}")

			latency = _measure_latency_ms(host.hostname, host.port)
			self._connect_host(host)
			self._status.connected = True
			self._status.active_host = host
			self._status.connected_since = time.time()
			self._status.latency_ms = latency
			return self.status

	def disconnect(self) -> None:
		with self._lock:
			if not self._status.connected or self._status.active_host is None:
				return

			host = self._status.active_host
			if host.protocol == VPNProtocol.WIREGUARD:
				self._disconnect_wireguard(host)
			elif host.protocol == VPNProtocol.OPENVPN:
				self._disconnect_openvpn()

			self._status = VPNStatus()

	def verify_connectivity(self, timeout_s: float = 1.2) -> bool:
		"""Quick liveness probe for internet reachability through the tunnel."""
		for endpoint in (("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53)):
			try:
				with socket.create_connection(endpoint, timeout=timeout_s):
					return True
			except OSError:
				continue
		return False

	def _connect_host(self, host: VPNHost) -> None:
		config = _expand_path(host.config_path)
		if not Path(config).exists():
			raise VPNError(f"VPN config file not found: {config}")

		if host.protocol == VPNProtocol.WIREGUARD:
			self._connect_wireguard(config)
			return
		if host.protocol == VPNProtocol.OPENVPN:
			self._connect_openvpn(config)
			return
		raise VPNError(f"Unsupported VPN protocol: {host.protocol}")

	def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:
		if self._runner is not None:
			return self._runner(cmd)

		return subprocess.run(
			cmd,
			capture_output=True,
			text=True,
			timeout=self.command_timeout_s,
			check=False,
		)

	def _require_binary(self, binary: str) -> None:
		if shutil.which(binary) is None:
			raise VPNError(f"Required command is missing: {binary}")

	def _connect_wireguard(self, config_path: str) -> None:
		self._require_binary("wg-quick")
		result = self._run(["sudo", "-n", "wg-quick", "up", config_path])
		if result.returncode != 0:
			raise VPNError(
				"WireGuard connect failed. "
				f"stderr={result.stderr.strip() or 'n/a'}"
			)

	def _disconnect_wireguard(self, host: VPNHost) -> None:
		self._require_binary("wg-quick")
		config_path = _expand_path(host.config_path)
		result = self._run(["sudo", "-n", "wg-quick", "down", config_path])
		if result.returncode != 0:
			raise VPNError(
				"WireGuard disconnect failed. "
				f"stderr={result.stderr.strip() or 'n/a'}"
			)

	def _connect_openvpn(self, config_path: str) -> None:
		self._require_binary("openvpn")
		pid_path = str(self._openvpn_pid_file)
		cmd = [
			"sudo",
			"-n",
			"openvpn",
			"--config",
			config_path,
			"--daemon",
			"--writepid",
			pid_path,
		]
		result = self._run(cmd)
		if result.returncode != 0:
			raise VPNError(
				"OpenVPN connect failed. "
				f"stderr={result.stderr.strip() or 'n/a'}"
			)

	def _disconnect_openvpn(self) -> None:
		if not self._openvpn_pid_file.exists():
			return

		try:
			pid = int(self._openvpn_pid_file.read_text(encoding="utf-8").strip())
		except (ValueError, OSError):
			return

		result = self._run(["sudo", "-n", "kill", "-TERM", str(pid)])
		if result.returncode != 0 and result.returncode != 1:
			raise VPNError(
				"OpenVPN disconnect failed. "
				f"stderr={result.stderr.strip() or 'n/a'}"
			)

		# Best-effort cleanup.
		for _ in range(20):
			if not _pid_exists(pid):
				break
			time.sleep(0.1)
		try:
			self._openvpn_pid_file.unlink(missing_ok=True)
		except OSError:
			pass


def _pid_exists(pid: int) -> bool:
	if pid <= 0:
		return False
	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False
	except PermissionError:
		return True
	return True


def quick_connect_best(
	*,
	country: Optional[str] = None,
	city: Optional[str] = None,
	protocol: Optional[VPNProtocol] = None,
) -> VPNStatus:
	"""Simple convenience API for scripts/UI wiring."""
	manager = VPNManager()
	return manager.connect(country=country, city=city, protocol=protocol)


__all__ = [
	"VPNCatalog",
	"VPNError",
	"VPNHost",
	"VPNManager",
	"VPNProtocol",
	"VPNStatus",
	"ensure_catalog_file",
	"load_catalog",
	"quick_connect_best",
]

