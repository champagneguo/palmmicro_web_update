import json
import os
import pandas as pd
import re
import requests
import sched
import sys
import time
import threading

from datetime import datetime
from zoneinfo import ZoneInfo

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract

from typing import Any, Callable, Dict, List, Optional

#单个定时任务类，封装任务及其调度信息
class PalmmicroTask:
	def __init__(self, name: str, func: Callable, interval: int, args: tuple = (), kwargs: Optional[Dict[str, Any]] = None, daemon: bool = True):
		self.name = name
		self.func = func
		self.interval = interval
		self.args = args
		self.kwargs = kwargs or {}
		self.daemon = daemon
		self.scheduler = sched.scheduler(time.time, time.sleep)
		self.thread: Optional[threading.Thread] = None
		self.is_running = False
		self.lock = threading.Lock()
		self.event_id: Optional[Any] = None
	
	def _execute_and_reschedule(self):
		#执行任务并重新调度自己
		try:
			self.func(*self.args, **self.kwargs)
		except Exception as e:
			print(f"任务 '{self.name}' 执行失败: {e}")
		finally:
			# 重新调度自己（如果任务仍在运行）
			with self.lock:
				if self.is_running:
					self.event_id = self.scheduler.enter(self.interval, 1, self._execute_and_reschedule)
	
	def _run_scheduler(self):
		#运行调度器循环
		while self.is_running:
			try:
				self.scheduler.run()
				# 当所有事件都执行完时，run()会返回，需要短暂休眠避免CPU空转
				if self.is_running and not self.scheduler.queue:
					time.sleep(0.1)
			except Exception as e:
				print(f"任务 '{self.name}' 调度器异常: {e}")
				break
	
	def start(self, delay: int = 0):
		#启动定时任务
		with self.lock:
			if self.is_running:
				print(f"任务 '{self.name}' 已经在运行中")
				return
			
			self.is_running = True
			# 首次调度，延迟delay秒后执行
			self.event_id = self.scheduler.enter(delay, 1, self._execute_and_reschedule)
			# 启动调度器线程
			self.thread = threading.Thread(target = self._run_scheduler, daemon = self.daemon, name = f"{self.__class__.__name__}-{self.name}")
			self.thread.start()
			print(f"任务 '{self.name}' 已启动，首次执行延迟 {delay} 秒")
	
	def stop(self, wait: bool = False):
		#停止定时任务
		with self.lock:
			if not self.is_running:
				print(f"任务 '{self.name}' 未在运行")
				return
			
			self.is_running = False
			# 从调度器队列中移除待执行的事件
			if self.event_id is not None:
				try:
					self.scheduler.cancel(self.event_id)
				except ValueError:
					pass  # 事件可能已经执行了
			print(f"任务 '{self.name}' 已停止")
		
		if wait and self.thread and self.thread.is_alive():
			self.thread.join(timeout = 5)
	
	def is_alive(self) -> bool:
		#检查任务是否在运行
		if self.thread is None:
			return False
		return self.is_running and self.thread.is_alive()
	
	@staticmethod
	def GetThreadsDataFrame() -> pd.DataFrame:
		#获取线程信息并包含栈帧信息（需要 sys._current_frames()）
		threads = threading.enumerate()
		current_thread = threading.current_thread()
		main_thread = threading.main_thread()
	
		# 获取所有线程的栈帧
		frames = sys._current_frames()
		thread_data: Dict[str, Any] = {'name': [], 'ident': [], 'alive': [], 'daemon': [], 'main': [], 'current': [], 'filename': [], 'line': [], 'function': []}
		for t in threads:
			thread_data['name'].append(t.name)
			thread_data['ident'].append(t.ident)
			thread_data['alive'].append(t.is_alive())
			thread_data['daemon'].append(t.daemon)
			thread_data['main'].append(t is main_thread)
			thread_data['current'].append(t is current_thread)
		
			# 获取栈帧信息
			if t.ident in frames:
				frame = frames[t.ident]
				thread_data['filename'].append(os.path.basename(frame.f_code.co_filename))
				thread_data['line'].append(frame.f_lineno)
				thread_data['function'].append(frame.f_code.co_name)
			else:
				thread_data['filename'].append(None)
				thread_data['line'].append(None)
				thread_data['function'].append(None)
		return pd.DataFrame(thread_data)

class PalmmicroStock:
	_global_lock = threading.Lock()

	def __init__(self, strSymbol: str, strName = None):
		self._data = {'symbol': strSymbol,
					  'LAST_price': None,
					  'VWAP_price': None,
					  'BUY_price': None,
					  'SELL_price': None,
					  'BUY_size': None,
					  'SELL_size': None,
					  'BUY_updated': False,
					  'SELL_updated': False
					 }
		if strName is None:
			self.strName = strSymbol
		else:
			self.strName = strName
	
	def set_value(self, key, value):
		self._data[key] = value
	
	def get_value(self, key):
		return self._data.get(key)
	
	def get_all_data(self):
		return self._data.copy()
	
	def update_data(self, new_data):
		if isinstance(new_data, dict):
			self._data.update(new_data)
	
	def delete_key(self, key):
		if key in self._data:
			del self._data[key]
			return True
		return False
	
	def clear_data(self):
		self._data.clear()

	def GetName(self) -> str:
		return self.strName

	def GetSymbol(self) -> str:
		strSymbol = self.get_value('symbol')
		if isinstance(strSymbol, str):
			return strSymbol
		return 'errorsymbol'

	def GetSymbolPrice(self, strType: str = 'LAST') -> Dict[str, float]:
		strSymbol = self.GetSymbol()
		fPrice = self.get_value(strType + '_price')
		if isinstance(fPrice, float):
			return {strSymbol: fPrice}
		return {strSymbol: 0.0}
	
	def GetSymbolSize(self, strType: str) -> Dict[str, int]:
		strSymbol = self.GetSymbol()
		iSize = self.get_value(strType + '_size')
		if isinstance(iSize, int):
			return {strSymbol: iSize}
		return {strSymbol: 0}
	
	def HasData(self, strType: str) -> bool:
		return self.get_value(strType + '_price') is not None and self.get_value(strType + '_size') is not None

	def IsUpdated(self, strType: str):
		if self.HasData(strType):
			return self.get_value(strType + '_updated')
		return False

	def SetUpdated(self, strType: str, bStatus: bool = True):
		if strType in self.GetTypeList():
			self.set_value(strType + '_updated', bStatus)
		
	def SetPrice(self, fPrice: float, strType: str = 'LAST') -> None:
		with PalmmicroStock._global_lock:
			fOld = self.get_value(strType + '_price')
			if fOld is None or abs(fOld - fPrice) > 0.0001:
				self.set_value(strType + '_price', fPrice)
				self.SetUpdated(strType)
			
	def SetSize(self, iSize: int, strType: str) -> None:
		with PalmmicroStock._global_lock:
			iOld = self.get_value(strType + '_size')
			if iOld is None or iOld != iSize:
				self.set_value(strType + '_size', iSize)
				self.SetUpdated(strType)

	@staticmethod
	def GetTypeList() -> List[str]:
		return ['BUY', 'SELL']

	@staticmethod
	def GetTypeDisplay(strType: str) -> str:
		if strType == 'SELL':
			return '平仓'
		return '开仓'

	@staticmethod
	def GetPeerType(strType: str) -> str:
		if strType == 'SELL':
			return 'BUY'
		return 'SELL'

	@staticmethod
	def IsLOF(strSymbol: str) -> bool:
		return strSymbol.startswith(("SZ16", "SH50"))
	
	@staticmethod
	def IsSymbolA(strSymbol: str) -> bool:
		pattern = r'^(SH|SZ|BJ)\d{6}$'
		if re.match(pattern, strSymbol):
			return True
		return False

	@staticmethod
	def IsFutureSymbol(strSymbol: str) -> bool:
		if strSymbol.startswith('hf_'):
			return True
		return False

	@staticmethod
	def ConvertYahooNetValueSymbol(strSymbol: str) -> str:
		# 匹配 ^XXX-YY 格式，并提取 XXX 部分
		pattern = r'^\^([A-Z]+)-[A-Z]{2}$'
		match = re.match(pattern, strSymbol)
		if match:
			return match.group(1)  # 返回符号主体部分
		else:
			return strSymbol  # 不符合格式则返回原字符串

	@staticmethod
	def JoinSymbols(arStock):
		return ','.join(arStock.keys())

	@staticmethod
	def GetExchangeTime(strName = 'NYSE'):
		exchange_timezones = {'NYSE': 'America/New_York','SZSE': 'Asia/Shanghai'}
		if strName not in exchange_timezones:
			raise ValueError(f'Unsupported exchange: {strName}')
		now_exchange = datetime.now(ZoneInfo(exchange_timezones[strName]))
		return now_exchange.hour * 100 + now_exchange.minute
		
#新浪股票类，继承自 PalmmicroStock, 使用新浪接口返回的原始数据字符串进行初始化, 格式如: 'var hq_str_sh600036="招商银行,36.50,36.48,...";'
class SinaStock(PalmmicroStock):
	arStock = {}

	def __init__(self, data_str):
		strSymbol, strName = self.ParseSymbol(data_str)
		super().__init__(strSymbol, strName)
		self.UpdateData(data_str)

	def Update(self, data_str: str) -> None:
		strSymbol, _ = self.ParseSymbol(data_str)
		if strSymbol == self.GetSymbol():
			self.UpdateData(data_str)

	@staticmethod
	def ParseSymbol(data_str):
		strSinaSymbol = 'unknown'
		strSymbol = 'errorsymbol'
		# 提取股票代码（从 var hq_str_ 后面截取）
		strCodeStart = 'var hq_str_'
		iCodeStart = data_str.find(strCodeStart)
		iStart = data_str.find('"')
		if iCodeStart != -1 and iStart != -1:
			code_part = data_str[iCodeStart + len(strCodeStart):iStart - 1]
			if code_part:
				if code_part.startswith('fx_'):
					strSymbol = code_part[-3:].upper()	# 'CNY'
				elif PalmmicroStock.IsFutureSymbol(code_part) or code_part.startswith('nf_'):
					strSymbol = code_part				# 'hf_CL, nf_AG0'
				elif code_part.startswith('gb_'):
					strSymbol = code_part[3:].upper()	# 'XOP'
				else:
					strSymbol = code_part.upper()		# 'SZ162411'
				strSinaSymbol = code_part
		return strSymbol, strSinaSymbol

	def __set_price_and_size(self, parts, last, buyp = None, sellp = None, buyv = None, sellv = None):
		self.SetPrice(float(parts[last]))
		if buyp is not None:
			self.SetPrice(float(parts[buyp]), 'BUY')
		if sellp is not None:
			self.SetPrice(float(parts[sellp]), 'SELL')
		if buyv is not None:
			self.SetSize(int(parts[buyv]), 'BUY')
		if sellv is not None:
			self.SetSize(int(parts[sellv]), 'SELL')

	def UpdateData(self, data_str):
		# 提取引号内的数据
		start = data_str.find('"')
		end = data_str.rfind('"')
		if start != -1 and end != -1 and start < end:
			data_content = data_str[start + 1:end]
			if data_content:
				# 分割数据
				strSinaSymbol = self.GetName()
				parts = data_content.split(',')
				if strSinaSymbol.startswith('fx_'):
					self.__set_price_and_size(parts, 8)
				elif self.IsFutureSymbol(strSinaSymbol):
					self.__set_price_and_size(parts, 0, 2, 3, 10, 11)
				elif strSinaSymbol.startswith('nf_'):
					self.__set_price_and_size(parts, 8, 6, 7, 11, 12)
				elif strSinaSymbol.startswith('gb_'):
					self.__set_price_and_size(parts, 1)
				else:
					if len(parts) >= 32:
						self.__set_price_and_size(parts, 3, 6, 7, 10, 20)
	
	@staticmethod
	def FetchData(strSymbols: str):
		strUrl = f'http://hq.sinajs.cn/list={strSymbols}'
		try:
			response = requests.get(strUrl, headers={'Referer': 'https://finance.sina.com.cn'})
			if response.status_code == 200:
				return response.text.split("\n")
			else:
				print('Failed to send sina request. Status code:', response.status_code)
		except requests.exceptions.RequestException as e:
			print('FetchSinaData error:', e)
		return False

	@classmethod
	def TaskLoop(cls, strSymbols):
		arLine = cls.FetchData(strSymbols)
		if arLine:
			for strLine in arLine:
				strSymbol, _ = cls.ParseSymbol(strLine)
				if strSymbol not in cls.arStock.keys():
					cls.arStock[strSymbol] = SinaStock(strLine)
				cls.arStock[strSymbol].UpdateData(strLine)
		#print(PalmmicroTask.GetThreadsDataFrame())

	@classmethod
	def TaskInit(cls, strSymbols: str = 'fx_susdcny,nf_AG0,nf_M0', interval: int = 19):
		cls.task = PalmmicroTask(cls.__name__, cls.TaskLoop, interval, (strSymbols, ))
		cls.task.start()
		return cls.arStock
	
	@classmethod
	def TaskFree(cls):
		cls.task.stop()

class TdxStock(PalmmicroStock):
	arStock = {}
	tq = None

	def __init__(self, strName):
		super().__init__(self.ConvertTdxSymbol(strName), strName)

	def Update(self) -> None:
		try:
			if self.tq is not None:
				data_dict = self.tq.get_market_snapshot(self.GetName(), ['ErrorId', 'Now', 'Jjjz', 'Buyp', 'Buyv', 'Sellp', 'Sellv'])
		except Exception as e:
			print(f"tq.get_market_snapshot异常: {e}")
			return
		#print(data_dict)
		if data_dict.get('ErrorId') == '0':
			self.SetPrice(float(data_dict['Buyp'][0]), 'BUY')
			self.SetPrice(float(data_dict['Sellp'][0]), 'SELL')
			fNow = float(data_dict['Now'])
			self.SetPrice(fNow)
			# 通达信溢价率: (最新价 - 基金净值) / 基金净值, 与通达信 More_YJL 字段口径一致
			fJjjz = data_dict.get('Jjjz')
			if fJjjz is not None and fJjjz != '':
				try:
					fJjjz = float(fJjjz)
					if fJjjz > 0:
						self.set_value('TDXPremium', (fNow - fJjjz) / fJjjz)
				except (TypeError, ValueError):
					pass
			iBuy = int(data_dict['Buyv'][0])
			iSell = int(data_dict['Sellv'][0])
			if self.IsSymbolA(self.GetSymbol()):
				iBuy *= 100
				iSell *= 100
				iBuy -= 50
				iSell -= 50
			self.SetSize(iBuy, 'BUY')
			self.SetSize(iSell, 'SELL')
		
	@staticmethod
	def ConvertTdxSymbol(strSymbol: str) -> str:
		strSymbol = strSymbol.strip()				# 去除前后空格
		if '.' in strSymbol:						# 如果包含 '.' 则分割
			parts = strSymbol.split('.')
			if len(parts) == 2:
				symbol = parts[0]					# 股票代码部分
				market = parts[1].upper()			# 市场部分，转为大写
				if market in ['SH', 'SZ', 'BJ']:	# 如果市场代码是 SH 或 SZ，返回市场+代码格式
					return f"{market}{symbol}"
				elif strSymbol == 'AGL8.SHF':
					return 'nf_AG0'
				elif strSymbol == 'USDCNY.OT':
					return 'CNY'
		return strSymbol							# 无法识别格式，返回原字符串

	""" 
	#从通达信拿汇率或者期货数据时才需要
	@staticmethod
	def ConvertToTdxName(strSymbol: str) -> str:
		#strSymbol = strSymbol.strip().upper()		# 去除前后空格
		if PalmmicroStock.IsSymbolA(strSymbol):
			market = strSymbol[:2]
			symbol = strSymbol[2:]
			return f"{symbol}.{market}"
		elif strSymbol == 'CNY':
			return 'USDCNY.OT'
		elif strSymbol == 'nf_AG0':
			return 'AGL8.SHF'
		return strSymbol							# 无法识别格式，返回原字符串
	"""

	@classmethod
	def TqInit(cls, strBlockCode: str = 'PLMM'):
		# 自动检测通达信安装路径(兼容 new_tdx_test / new_tdx64 等目录)
		for strTdxDir in ('D:/new_tdx_test', 'D:/new_tdx64'):
			strPluginDir = f'{strTdxDir}/PYPlugins/user'
			if os.path.isfile(f'{strPluginDir}/tqcenter.py'):
				sys.path.append(strPluginDir)
				print(f'使用通达信插件目录: {strPluginDir}')
				break
		try:
			from tqcenter import tq	# type: ignore
			tq.initialize(__file__)
			cls.tq = tq
		except ImportError:
			print('⚠️ tqcenter 模块不存在, TQ 功能不可用')
		except RuntimeError as e:
			print(f"⚠️ TQ 初始化失败: {e}")
		except SystemExit:
			# ErrorId=20 导致的退出
			print('⚠️ TQ 检测到致命错误')
			# 这里程序会退出，所以后续代码不会执行
		except Exception as e:
			print(f"⚠️ TQ 未知错误: {e}")

		# 后续使用
		if cls.tq is None:
			return None

		#match_stkinfo = tq.get_match_stkinfo('USDCNY')
		#print(match_stkinfo)
		block_stocks = tq.get_stock_list_in_sector(strBlockCode, 1)
		#print(block_stocks)

		if len(block_stocks) > 0:
			ar = []
			for strName in block_stocks:
				stock = TdxStock(strName)
				strSymbol = stock.GetSymbol()
				cls.arStock[strSymbol] = stock
				ar.append(strName)
			sub_hq = tq.subscribe_hq(ar, cls.TqCallback)
			cls.TqDebug(sub_hq)
		return cls.arStock

	@classmethod
	def TqFree(cls):
		if cls.tq is not None:
			cls.tq.close()

	@classmethod
	def TqDebug(cls, strDebug: str) -> None:
		try:
			if cls.tq is not None:
				cls.tq.send_message(strDebug)
		except Exception as e:
			print(f"TqDebug异常: {e}")

	"""
	@classmethod
	def _refresh_cache(cls, strMarket):
		try:
			cache = tq.refresh_cache(strMarket, True)
		except Exception as e:
			print(f"_refresh_cache异常: {e}")
			return
		cache_json = json.loads(cache)
		if cache_json['ErrorId'] != '0':
			print(strMarket, cache_json['Error'])
	"""

	@classmethod
	def TqCallback(cls, data_str):
		code_json = json.loads(data_str)
		strSymbol = cls.ConvertTdxSymbol(code_json.get('Code'))
		cls.arStock[strSymbol].Update()
		"""
		#cls._refresh_cache('AG')
		#cls._refresh_cache('QH')
		"""

class TdxFutureEtfStock(TdxStock):
	"""通达信 FUTURESETF 板块(期货ETF)行情, 用于 dashboard 展示通达信接口数据与溢价率"""
	arStock = {}
	# 期货ETF 中文名映射, 未收录的代码回退显示为代码本身
	NAME_MAP = {
		'SZ159985': '豆粕ETF',
		'SZ159980': '有色金属ETF',
		'SZ159981': '能源化工ETF',
	}
	# 底层主力合约(ETF 对应的期货品种主力合约); 有色/能化跟踪多品种指数, 无单一主力合约
	UNDERLYING_MAP = {
		'SZ159985': '豆粕主力',
		'SZ159980': '铜/铝/锌/铅/镍/锡主力',
		'SZ159981': 'PTA/甲醇/动力煤/玻璃主力',
	}
	# ETF 代码 → 主力合约内部代码(新浪 nf_ 主力连续), 用于显示实时主力价格
	MAIN_CONTRACT_MAP = {
		'SZ159985': 'nf_M0',
	}
	# 主力价格数据源: {内部代码: PalmmicroStock}, 由 app 启动时注入 SinaStock.arStock
	main_price_source = {}
	# 历史溢价率序列缓存: {strSymbol: {'series': [premium...], 'ts': monotonic}}
	_history_cache = {}

	def __init__(self, strName):
		super().__init__(strName)
		strSymbol = self.GetSymbol()
		self._data['Name'] = self.NAME_MAP.get(strSymbol, strSymbol)
		self._data['Underlying'] = self.UNDERLYING_MAP.get(strSymbol, '')
		self._data['Now'] = None
		self._data['Jjjz'] = None
		self._data['Premium'] = None
		self._data['Time'] = ''

	def Update(self) -> None:
		"""拉取通达信快照, 保存最新价/基金净值/溢价率/买卖盘"""
		if self.tq is None:
			return
		try:
			data_dict = self.tq.get_market_snapshot(self.GetName(), ['ErrorId', 'Now', 'Jjjz', 'Buyp', 'Buyv', 'Sellp', 'Sellv'])
		except Exception as e:
			print(f"tq.get_market_snapshot(FUTURESETF)异常: {e}")
			return
		if data_dict.get('ErrorId') != '0':
			return
		try:
			fNow = float(data_dict['Now'])
			self._data['Now'] = fNow
			self._data['Buyp'] = float(data_dict['Buyp'][0])
			self._data['Sellp'] = float(data_dict['Sellp'][0])
			self._data['Buyv'] = int(data_dict['Buyv'][0])
			self._data['Sellv'] = int(data_dict['Sellv'][0])
		except (KeyError, TypeError, ValueError, IndexError):
			pass
		fJjjz = data_dict.get('Jjjz')
		if fJjjz is not None and fJjjz != '':
			try:
				fJjjz = float(fJjjz)
				self._data['Jjjz'] = fJjjz
				if fJjjz > 0 and self._data.get('Now') is not None:
					# 通达信溢价率: (最新价 - 基金净值) / 基金净值, 与通达信 More_YJL 字段口径一致
					self._data['Premium'] = (self._data['Now'] - fJjjz) / fJjjz
			except (TypeError, ValueError):
				pass
		self._data['Time'] = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%H:%M:%S')

	@classmethod
	def TqInitFutureEtf(cls, strBlockCode: str = 'FUTURESETF'):
		"""初始化 FUTURESETF 板块, 复用 TdxStock 已建立的通达信连接"""
		cls.tq = TdxStock.tq
		if cls.tq is None:
			print('⚠️ 通达信连接未建立, FUTURESETF 板块不可用')
			return cls.arStock
		try:
			block_stocks = cls.tq.get_stock_list_in_sector(strBlockCode, 1)
		except Exception as e:
			print(f"获取 {strBlockCode} 板块成分股异常: {e}")
			return cls.arStock
		if not block_stocks:
			print(f'没有找到通达信自定义板块 {strBlockCode}, dashboard 期货ETF表格将为空。')
			return cls.arStock
		ar = []
		for strName in block_stocks:
			stock = cls(strName)
			strSymbol = stock.GetSymbol()
			cls.arStock[strSymbol] = stock
			ar.append(strName)
		try:
			sub_hq = cls.tq.subscribe_hq(ar, cls.TqFutureEtfCallback)
			cls.TqDebug(sub_hq)
		except Exception as e:
			print(f"订阅 {strBlockCode} 行情异常: {e}")
		return cls.arStock

	@classmethod
	def TqFutureEtfCallback(cls, data_str):
		code_json = json.loads(data_str)
		strSymbol = cls.ConvertTdxSymbol(code_json.get('Code'))
		stock = cls.arStock.get(strSymbol)
		if stock is not None:
			stock.Update()

	@classmethod
	def GetDisplayDataFrame(cls) -> pd.DataFrame:
		"""返回 dashboard 展示用的 DataFrame(中文列名, 溢价率降序)"""
		columns = ['代码', '底层主力合约', '主力价格', '最新价', '基金净值', '溢价率', '历史百分位', '买一价', '卖一价', '买一量', '卖一量', '更新时间', '报告链接']
		rows = []
		for strSymbol, stock in cls.arStock.items():
			data = stock.get_all_data()
			fMain = None
			strMain = cls.MAIN_CONTRACT_MAP.get(strSymbol)
			if strMain:
				main_stock = cls.main_price_source.get(strMain)
				if main_stock is not None:
					fMain = main_stock.get_value('LAST_price')
			fPct = cls.GetPremiumPercentile(strSymbol)
			rows.append({
				'代码': f"{strSymbol}({data.get('Name', strSymbol)})",
				'底层主力合约': data.get('Underlying', ''),
				'主力价格': fMain,
				'最新价': data.get('Now'),
				'基金净值': data.get('Jjjz'),
				'溢价率': data.get('Premium'),
				'历史百分位': f"{fPct:.1f}%" if fPct is not None else '',
				'买一价': data.get('Buyp'),
				'卖一价': data.get('Sellp'),
				'买一量': data.get('Buyv'),
				'卖一量': data.get('Sellv'),
				'更新时间': data.get('Time', ''),
				'报告链接': f"https://fundf10.eastmoney.com/jjgg_{strSymbol[-6:]}_3.html",
			})
		if not rows:
			return pd.DataFrame(columns = columns)
		# 溢价率降序, 无溢价率的排最后
		rows.sort(key = lambda r: (not isinstance(r['溢价率'], (int, float)), -(r['溢价率'] if isinstance(r['溢价率'], (int, float)) else 0.0)))
		df = pd.DataFrame(rows)
		# None 在 DataFrame 中会变成 NaN(仍是 float), 需用 pd.isna 一并排除
		def _num(x):
			return isinstance(x, (int, float)) and not pd.isna(x)
		for col in ('最新价', '基金净值', '买一价', '卖一价'):
			df[col] = df[col].apply(lambda x: f"{x:.3f}" if _num(x) else '')
		df['主力价格'] = df['主力价格'].apply(lambda x: f"{x:.2f}" if _num(x) else '')
		df['溢价率'] = df['溢价率'].apply(lambda x: f"{x * 100.0:.2f}%" if _num(x) else '')
		for col in ('买一量', '卖一量'):
			df[col] = df[col].apply(lambda x: str(int(x)) if _num(x) else '')
		return df

	@classmethod
	def GetHistoricalPremium(cls, strSymbol, iCount: int = 250):
		"""返回历史溢价率序列 [{date, price, nav, premium}], 溢价率 = 日K收盘 / 天天基金单位净值 - 1"""
		arNav = cls._fetch_nav_history(strSymbol[-6:], iCount)
		arPrice = cls._fetch_close_history(strSymbol, iCount)
		if not arNav:
			print(f"历史溢价率 {strSymbol}: 净值数据为空(天天基金)")
		if not arPrice:
			print(f"历史溢价率 {strSymbol}: 价格数据为空(新浪日K)")
		series = []
		for date in sorted(set(arNav) & set(arPrice)):
			fNav = arNav[date]
			if fNav <= 0:
				continue
			fPrice = arPrice[date]
			series.append({
				'date': date,
				'price': round(fPrice, 4),
				'nav': round(fNav, 4),
				'premium': round(fPrice / fNav - 1.0, 6),
			})
		return series

	@staticmethod
	def _fetch_nav_history(strFund, iCount):
		"""天天基金历史单位净值(分页, 每页最多20条), 返回 {date(YYYY-MM-DD): nav}"""
		ar = {}
		page_size = 20
		pages = (iCount + page_size - 1) // page_size
		for page in range(1, pages + 1):
			try:
				resp = requests.get(
					'http://api.fund.eastmoney.com/f10/lsjz',
					params = {'fundCode': strFund, 'pageIndex': page, 'pageSize': page_size},
					headers = {'Referer': 'http://fundf10.eastmoney.com/'},
					timeout = 15
				)
				data = resp.json()
			except Exception as e:
				print(f"天天基金历史净值获取失败(page {page}): {e}")
				break
			lst = (data.get('Data') or {}).get('LSJZList') or []
			if not lst:
				break
			for row in lst:
				fNav = row.get('DWJZ')
				if fNav in (None, ''):
					continue
				try:
					ar[str(row.get('FSRQ'))] = float(fNav)
				except (TypeError, ValueError):
					continue
			if len(lst) < page_size:
				break
		return ar

	@staticmethod
	def _fetch_close_history(strSymbol, iCount):
		"""新浪日K收盘价, 返回 {date(YYYY-MM-DD): close}"""
		try:
			resp = requests.get(
				'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData',
				params = {'symbol': strSymbol.lower(), 'scale': 240, 'ma': 'no', 'datalen': iCount},
				headers = {'Referer': 'https://finance.sina.com.cn'},
				timeout = 15
			)
			data = resp.json()
		except Exception as e:
			print(f"新浪日K获取失败: {e}")
			return {}
		ar = {}
		for row in data if isinstance(data, list) else []:
			try:
				ar[str(row.get('day'))] = float(row.get('close'))
			except (TypeError, ValueError):
				continue
		return ar

	@classmethod
	def _get_history_premiums(cls, strSymbol, iCount: int = 250, ttl: int = 3600):
		"""缓存的历史溢价率序列(约1小时有效), 返回 [premium, ...]"""
		now = time.monotonic()
		entry = cls._history_cache.get(strSymbol)
		if entry and now - entry['ts'] < ttl:
			return entry['series']
		series = cls.GetHistoricalPremium(strSymbol, iCount)
		premiums = [r['premium'] for r in series if isinstance(r.get('premium'), (int, float))]
		cls._history_cache[strSymbol] = {'series': premiums, 'ts': time.monotonic()}
		return premiums

	@classmethod
	def GetPremiumPercentile(cls, strSymbol, iCount: int = 250):
		"""当前溢价率在历史分布中的百分位(0~100), 用于评估高估/低估; 无数据返回 None"""
		stock = cls.arStock.get(strSymbol)
		if stock is None:
			return None
		cur = stock.get_value('Premium')
		if not isinstance(cur, (int, float)):
			return None
		premiums = cls._get_history_premiums(strSymbol, iCount)
		if not premiums:
			return None
		below = sum(1 for p in premiums if p < cur)
		return round(below / len(premiums) * 100.0, 1)

class PalmmicroWrapper(EWrapper):
	def __init__(self, client, arMapping = None):
		self.client = client
		if arMapping is not None:
			self.arSymbols = list(set(s for sublist in arMapping.values() for s in sublist))
			self.arSymbols = [s for s in self.arSymbols if not s.startswith('nf_')]
			TdxStock.TqDebug(','.join(self.arSymbols))
			self.arStock = {}

	arFutureDict = {'hf_CL': 'MCL202610',
					'hf_GC': 'MGC202612',
					'hf_ES': 'MES202609',
					'hf_NQ': 'MNQ202609'
				   }

	@classmethod
	def GetSymbolDisplay(cls, strSymbol):
		if PalmmicroStock.IsFutureSymbol(strSymbol):
			return cls.arFutureDict[strSymbol]
		return strSymbol
	
	@classmethod
	def GetFutureSymbol(cls, strSymbol):
		combined = cls.arFutureDict[strSymbol]
		prefix, date = re.match(r'([A-Za-z]+)(\d+)', combined).groups()	# type: ignore
		return prefix, date, combined

	def nextValidId(self, orderId: int):
		self.iOrderId = orderId
		self.iRequestId = 0
		self.arContract = {}
		for strSymbol in self.arSymbols:
			contract = Contract()
			if PalmmicroStock.IsFutureSymbol(strSymbol):
				prefix, date, combined = self.GetFutureSymbol(strSymbol)
				contract.secType = 'FUT'
				if strSymbol == 'hf_CL':
					contract.exchange = 'NYMEX'
				elif strSymbol == 'hf_GC':
					contract.exchange = 'COMEX'
				elif strSymbol == 'hf_ES' or strSymbol == 'hf_NQ':
					contract.exchange = 'CME'
				contract.lastTradeDateOrContractMonth = date
			else:
				prefix = strSymbol
				combined = strSymbol
				contract.secType = 'STK'
				contract.exchange = self.GetStockContractExchange()
			contract.symbol = prefix
			contract.currency = 'USD'
			self.arContract[combined] = contract
			self.iRequestId += 1
			#self.client.reqMktData(self.iRequestId, contract, '233', False, False, [])
			self.client.reqMktData(self.iRequestId, contract, '', False, False, [])
			self.arStock[self.iRequestId] = IbkrStock(combined)

	def error(self, reqId, errorCode, errorString, *args):
		print('Error:', reqId, errorCode, errorString)
		if args:
			TdxStock.TqDebug(args[0])

	def connectionClosed(self):
		TdxStock.TqDebug('IB连接已关闭')

	def tickPrice(self, reqId, tickType, price, attrib):
		if price > 0.0:
			stock = self.arStock[reqId]
			if tickType == 1:  # Bid price
				stock.SetPrice(price, 'BUY')
			elif tickType == 2:  # Ask price
				stock.SetPrice(price, 'SELL')
			elif tickType == 4: # Last price
				stock.SetPrice(price)
			else:
				...
				#print(stock.GetName(), price, tickType)

	def tickSize(self, reqId, tickType, size):
		stock = self.arStock[reqId]
		iSize = int(size)
		if tickType == 0:  # Bid size
			stock.SetSize(iSize, 'BUY')
		elif tickType == 3:  # Ask size
			stock.SetSize(iSize, 'SELL')
		else:
			...
			#print(stock.GetName(), iSize, tickType)

	def tickString(self, reqId, tickType, value):
		stock = self.arStock[reqId]
		if tickType == 48:  # RT_VOLUME
			arParts = value.split(';')
			if len(arParts) >= 6 and arParts[4] != '': 
				fPrice = float(arParts[4])
				(strSymbol, fOld), = stock.GetNamePrice('VWAP').items()
				if strSymbol.startswith('MES') or strSymbol.startswith('MNQ'):
					fPrice = round(4.0 * fPrice) / 4.0
				fPrice = round(fPrice, 2)
				if fOld is None or abs(fPrice - fOld) > 0.005:
					stock.SetPrice(fPrice, 'VWAP')
					#print(strSymbol, 'VWAP', fPrice)
		else:
			...
			#print(stock.GetName(), value, tickType)

	def marketDataType(self, reqId: int, marketDataType: int):
		if marketDataType != 1:
			stock = self.arStock[reqId]
			print(stock.GetName(), '无实时数据')

	def FreeMktData(self):
		for iRequestId in self.arStock.keys():
			self.client.cancelMktData(iRequestId)

	def GetStocks(self):
		return self.arStock

	@staticmethod
	def GetStockContractExchange():
		iTime = PalmmicroStock.GetExchangeTime()
		if iTime >= 350 and iTime < 2000:
			return 'SMART'
		return 'OVERNIGHT'

class IbkrStock(PalmmicroStock):
	def __init__(self, strName):
		if strName.startswith('MCL'):
			strSymbol = 'hf_CL'
		elif strName.startswith('MES'):
			strSymbol = 'hf_ES'
		elif strName.startswith('MGC'):
			strSymbol = 'hf_GC'
		elif strName.startswith('MNQ'):
			strSymbol = 'hf_NQ'
		else:
			strSymbol = strName
		super().__init__(strSymbol, strName)

	def GetNamePrice(self, strType: str = 'LAST') -> Dict[str, float]:
		(_, fPrice), = self.GetSymbolPrice(strType).items()
		return {self.GetName(): fPrice}

	@classmethod
	def InitAPI(cls, arMapping: Dict[str, List[str]], port = 7497, id = 2):	# arMapping from PalmmicroAPI.GetMapping(), usually id 0 for master API, 1 for excel
		cls.client = EClient(PalmmicroWrapper(None))
		cls.client.wrapper = PalmmicroWrapper(cls.client, arMapping)
		cls.client.connect('127.0.0.1', port, clientId = id)
		cls.ib_thread = threading.Thread(target = cls.client.run, daemon = True, name = f"{cls.__name__}-{port}-{id}")
		cls.ib_thread.start()
		return cls.client.wrapper.GetStocks()

	@classmethod
	def FreeAPI(cls):
		cls.client.wrapper.FreeMktData()
		cls.client.disconnect()
		if cls.ib_thread.is_alive():
			cls.ib_thread.join(timeout = 5)
