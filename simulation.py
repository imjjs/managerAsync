import ConfigParser
import os.path
import time
import datetime
import logging
import threading
import copy
import math
import random
import ast
from abc import ABCMeta, abstractmethod

from constants import *
from dto.model import ResourceAllocationInput, SimulationTask
from resource_allocation_policies import create_scheduler
# from simulation_tracker import *

from matlab_config_generator.input import getRandomHeatPercent
from estimator.execution_time_estimator import *


class Simulation(object):
	__metaclass__ = ABCMeta

	def __init__(self, sim_file, cpu, sim_count, deadline_in_secs):
		sim_conf_file = os.path.join(os.path.dirname(__file__), SIMULATION_CONF_DIR + sim_file)
		self.sim_conf = ConfigParser.ConfigParser();
		self.sim_conf.read(sim_conf_file);
		self.state = SIMULATION_STATE_INACTIVE
		suffix = '_' + str(time.time())
		self.sim_name = sim_file + suffix
		self.max_task_id = -1
		self.mu = 0.0
		self.var = 0.0
		self.N = 0
		file_name = './output/res_' + self.sim_name
		self.fo = open(file_name, "wb")
		file_name = './output/total_' + self.sim_name
		self.to = open(file_name, "wb")

		self.number_of_sims = sim_count  # int(self.sim_conf.get('PROCESS_DETAILS', 'NUMBER_OF_SIMS'))
		self.margin = float(self.sim_conf.get('PROCESS_DETAILS', 'MARGIN'))
		self.command = self.sim_conf.get('SIM_INPUT', 'SIMULATION_COMMAND')
		self.strategy = self.sim_conf.get('SIM_INPUT', 'STRATEGY')
		self.remaining_number_of_sims = self.number_of_sims
		self.release_count = 4
		self.error = 0.0

		self.resource_size = cpu

		# deadline_in_secs = int(self.sim_conf.get('SIM_INPUT', 'DEADLINE'))
		self.margin_value = deadline_in_secs * 1000 * self.margin
		self.creation_time = datetime.datetime.now()
		self.deadline = self.creation_time + datetime.timedelta(0, deadline_in_secs)
		# schedule change should not happen after margin, let it finish
		self.schedule_change_deadline = self.creation_time + datetime.timedelta(0, deadline_in_secs * (
		1 - self.margin))

		# add_simulation(self.sim_name, self.remaining_number_of_sims,0)
		self.image = self.sim_conf.get('PROCESS_DETAILS', 'IMAGE_NAME')
		self.working_dir = self.sim_conf.get('PROCESS_DETAILS', 'WORKING_DIR')

		self.environ = []
		self.environ.append('sim_name=' + self.sim_name)
		self.environ.append("strategy=" + self.strategy)
		self.environ.append("aggregator_ip=" + self.sim_conf.get('PROCESS_DETAILS', 'AGGREGATOR_IP'))
		self.environ.append("aggregator_port=" + self.sim_conf.get('PROCESS_DETAILS', 'AGGREGATOR_PORT'))

		self.tasks = {}
		logging.info('setting up simulation tasks ...')
		self.setup()
		self.populateTasks()
		self.finish_count = 0
		logging.info('Simulation deadline: ' + str(self.deadline))

	def getName(self):
		return self.sim_name

	def getTasks(self):
		return self.tasks

	def getResourceSize(self):
		return self.resource_size

	def getDeadline(self):
		return self.deadline

	def decrementRemainingCount(self):
		self.remaining_number_of_sims = self.remaining_number_of_sims - 1

	def endSimulation(self):
		logging.info('ENDING the simulation now')
		self.state = SIMULATION_STATE_FINISHED
		self.ending_time = datetime.datetime.now()

	def scheduleSimulation(self):
		self.state = SIMULATION_STATE_SCHEDULED
		self.schedule_time = datetime.datetime.now()

	def failSimulation(self):
		self.state = SIMULATION_STATE_FAILED
		self.failure_time = datetime.datetime.now()

	@abstractmethod
	def updateRunTimeError(self, task_id, exec_time):
		return

	@abstractmethod
	def updateEstimatedExecutionTime(self):
		return

	@abstractmethod
	def populateTasks(self):
		# will modify later
		return


class FiveRoomSimulation(Simulation):
	def __init__(self, sim_file, cpu, sim_count, deadline):
		super(FiveRoomSimulation, self).__init__(sim_file, cpu, sim_count, deadline)

	def setup(self):
		self.sim_type = "FIVE_ROOM"
		number_of_heaters = self.sim_conf.get('SIM_INPUT', 'NUMBER_OF_HEATERS')
		self.environ.append("number_of_heaters=" + number_of_heaters)
		sampling_rate = self.sim_conf.get('SIM_INPUT', 'SAMPLING_RATE')
		self.environ.append("sampling_rate=" + sampling_rate)
		# Execution time does not depend on simulation parameter
		self.input_exec_time = int(self.sim_conf.get('SIM_INPUT', 'EST_RUNNING_TIME'))
		self.error = 0.0

	def populateTasks(self):
		exec_time = float(self.sim_conf.get('SIM_INPUT', 'EST_RUNNING_TIME'))
		for i in range(self.number_of_sims):
			# heat_rate_inputs = []
			# for j in range(0,5):
			#	heat_rate_inputs.append(getRandomHeatPercent(5,40))
			# task_dict[i] = (heat_rates)
			# self.environ.append("heat_rates" + str(i+1) + "=" + str(_heat_rates[i]))
			task = SimulationTask()
			task.id = i
			task.exec_param = None
			task.exec_time = int(self.input_exec_time)
			# task.actual_execution_time = -1
			task.status = SIMULATION_STATE_SCHEDULED
			task.sim_environ = copy.copy(self.environ)
			task.sim_environ.append("sim_id=" + str(i))
			self.tasks[i] = task

	def updateEstimatedExecutionTime(self):
		# constant
		for taskname, task in self.getTasks().iteritems():
			if task.status == SIMULATION_STATE_SCHEDULED:
				task.exec_time = int(self.input_exec_time * (1 + self.error))

	def updateRunTimeError(self, task_id, exec_time):
		old_error = self.error
		self.error, self.mu, self.var, self.N = find_average_error(self.input_exec_time, int(exec_time),
									   self.mu, self.var, self.N)
		logging.warn('sim: ' + self.getName() + ' old error: ' + str(old_error) + ', new error: ' + str(
			self.error) + ' , N: ' + str(self.N))


class SumoTrafficSimulation(Simulation):
	def __init__(self, sim_file, cpu, sim_count, deadline):
		super(SumoTrafficSimulation, self).__init__(sim_file, cpu, sim_count, deadline)

	def setup(self):
		self.sim_type = "SUMO_TRAFFIC"
		param = self.sim_conf.get('SIM_INPUT', 'PARAM1')
		self.exec_params = map(int, param.split())
		logging.debug('Input param: ' + str(self.exec_params))
		exec_times = self.sim_conf.get('SIM_INPUT', 'EST_RUNNING_TIME')
		self.exec_times = map(int, exec_times.split())
		logging.debug('Input exec time: ' + str(self.exec_times))
		self.exec_time_table = estimate_exec_time_table(self.exec_params, self.exec_times, self.strategy)
		self.error = 0.0
		logging.debug('Table  time: ' + str(self.exec_time_table))
		logging.info('exec time table size :  ' + str(len(self.exec_time_table)))

	def populateTasks(self):
		start_count = int(self.sim_conf.get('SIM_INPUT', 'NUMBER_OF_VEHICLES_START'))
		step = int(self.sim_conf.get('SIM_INPUT', 'NUMBER_OF_VEHICLES_STEP'))
		last_count = start_count
		for i in range(self.number_of_sims):
			rate = round((1000.0 / last_count), 5)
			task = SimulationTask()
			task.id = i
			task.exec_param = last_count
			task.exec_time = self.exec_time_table[last_count]
			# task.actual_execution_time = -1
			last_count = last_count + step
			task.status = SIMULATION_STATE_SCHEDULED
			task.sim_environ = copy.copy(self.environ)
			task.sim_environ.append("rate=" + str(rate))
			task.sim_environ.append("sim_id=" + str(i))
			self.tasks[i] = task

	def updateEstimatedExecutionTime(self):
		# constant
		for taskname, task in self.getTasks().iteritems():
			if task.status == SIMULATION_STATE_SCHEDULED:
				task.exec_time = int(self.exec_time_table[task.exec_param] * (1 + self.error))
				logging.debug('task_id: ' + str(taskname) + ', exec time: ' + str(task.exec_time))

	def updateRunTimeError(self, task_id, exec_time):
		task = self.getTasks().get(task_id)
		old_error = self.error
		self.error, self.mu, self.var, self.N = find_average_error(self.exec_time_table[task.exec_param],
									   int(exec_time), self.mu, self.var, self.N)
		logging.info('sim: ' + self.getName() + ' old error: ' + str(old_error) + ', new error: ' + str(
			self.error) + ' , N: ' + str(self.N))


class OptimizationSimulation(Simulation):
	def __init__(self, sim_file, cpu, sim_count, deadline):
		super(OptimizationSimulation, self).__init__(sim_file, cpu, sim_count, deadline)

	def setup(self):
		self.sim_type = "SUMO_OPTIMIZATION"
		# Execution time does not depend on simulation parameter
		self.input_exec_time = 0  # int(self.sim_conf.get('SIM_INPUT', 'EST_RUNNING_TIME'))
		self.error = 0.0
		self.id = 0

		##################################
		self.pick_mark = 0
		self.rand_pick = False
		self.adaptive = False
		self.K0 = 12
		self.T = 0
		self.dim = 18
		self.range = (0, 21)
		self.step = 1

		self.start_time = time.time()
		self.timeLine = open('kcd21k13.txt','a',0)

		self.updating = None
		self.processing = None
		self.updating_params = None
		self.result = 0
		self.stage = 1
		self.numParams = (self.range[1] - self.range[0]) / self.step
		self.num_sims = 0
		self.directions = []
		self.directions_outcome = []
		self.directions_count = []
		##################################
		tmp = []
		for i in range(self.dim):
			tmp.append(self.range[1] - 1)
			self.directions.append(-1)
			self.directions_outcome.append(-5.0)
			self.directions_count.append(0)
		self.params = tuple(tmp)

	def randPicking(self):
		self.selected = []
		while len(self.selected) != self.K:
			idx = random.randint(0, self.dim - 1)
			if idx in self.selected:
				continue
			self.selected.append(idx)
	def randPicking_async(self):
		while True:
			idx = random.randint(0, self.dim - 1)
			if idx not in self.selected:
				self.selected.append(idx)
				self.selected = self.selected[1:]
				self.updating = idx
				break
			self.processing = 0
			print "new updating:", self.updating

	def picking(self):
		self.selected = []
		for idx in range(self.K):
			self.selected.append((idx + self.pick_mark) % self.dim)
		assert len(self.selected) == self.K
		print "selected :" + str(self.selected)
		self.pick_mark = (self.K + self.pick_mark) % self.dim

	def picking_async(self):
		self.updating = self.pick_mark
		self.processing = 0
		self.pick_mark = (self.pick_mark + 1) % self.dim
		print "new updating:", self.updating

	def stage1(self):

		if self.adaptive == False:
			self.K = self.K0 + 1
		else:
			self.K = int(self.K0 * math.exp(-1 * self.T)) + 1
		self.num_sims = self.number_of_sims
		num_sims = self.num_sims

		if True == self.rand_pick:
			self.randPicking()
		else:
			self.picking()


		print "num of params:", self.numParams

		for i in self.selected:
			for j in range(self.range[0], self.range[1], self.step):
				self.new_task(i, j, self.params)
				num_sims -= 1
				assert num_sims >= 0

		for i in range(num_sims):
			self.new_task(-1,0,self.params)

	def new_task(self, index, value, params):
		task = SimulationTask()
		print "creating task:" + str(index) + " " + str(value) + " " + str(params)
		self.id += 1

		print "created task id " + str(self.id)
		logging.info("created task id " + str(self.id))

		task.id = self.id
		task.exec_param = None
		# task.exec_time = int(self.input_exec_time)
		# task.actual_execution_time = -1
		task.status = SIMULATION_STATE_SCHEDULED
		task.sim_environ = copy.copy(self.environ)
		task.sim_environ.append("sim_id=" + str(task.id))
		task.input_params = "[" + str(index) + "," + str(value) + "," + str(params).replace(" ", "") + "]"
		print task.input_params
		task.sim_environ.append("param=" + task.input_params)
		self.tasks[self.id] = task

	def populateTasks(self):
		# exec_time = float(self.sim_conf.get('SIM_INPUT', 'EST_RUNNING_TIME'))
		logging.info('populating tasks .. ')
		logging.debug('number os sims input: ' + str(self.number_of_sims))

		self.stage1()

	def updateResult(self, new_result):
		assert new_result > self.result
		self.result = new_result
		self.T = 0


	def createTask(self, last_task_id, results):
		last_task = self.tasks.get(last_task_id)
		input_params = last_task.input_params
		print (
			"received: taskid: " + str(last_task_id) + " input: " + str(input_params) + " output: " + results)
		ret = ast.literal_eval(results)
		updated = ret[0]
		param = ret[1]
		result = ret[2]
		params = ast.literal_eval(input_params)[2]
		
		if updated >= 0:
			self.directions_count[updated] += 1
			assert self.directions_count[updated] <= self.numParams
			if result > self.directions_outcome[updated]:
				self.directions[updated] = param
				self.directions_outcome[updated] = result

			if result >= self.result:
				self.result = result
				self.T = 0
				print "found new sub-optimal solution:", updated, param

			if self.numParams == self.directions_count[updated]:  #last updated
				assert self.directions[updated] != -1
				tmp = list(self.params)
				tmp[updated] = self.directions[updated]
				self.params = tuple(tmp)
				self.directions[updated] = -1
				self.directions_outcome[updated] = -5.0
				self.directions_count[updated] = 0

		if self.updating == None:
			if True == self.rand_pick:
				self.randPicking_async()
			else:
				self.picking_async()
			self.updating_params = self.params

		assert self.updating != None
		assert self.processing != None
		assert self.updating_params != None  #TODO:: creating the data structure for the sub-optimal problem
		assert self.processing < self.numParams

		task = SimulationTask()
		# self.max_task_id += 1
		# task.id = self.max_task_id
		task.id = self.id
		task.exec_param = None
		task.exec_time = int(self.input_exec_time)
		# task.actual_execution_time = -1
		task.status = SIMULATION_STATE_SCHEDULED
		task.sim_environ = copy.copy(self.environ)
		task.sim_environ.append("sim_id=" + str(self.id))
		task.input_params = "[" + str(self.updating) + "," + str(
			self.range[0] + self.processing * self.step) + "," + str(
			self.updating_params).replace(" ", "") + "]"
		task.sim_environ.append("param=" + task.input_params)
		self.tasks[self.id] = task
		self.id += 1
		print "creating task:", task.input_params
		self.processing += 1
		if self.processing == self.numParams:
			self.processing = None
			self.updating = None
			self.updating_params = None
		return task

	def updateEstimatedExecutionTime(self):
		# constant
		print "do no exectime update"

	def updateRunTimeError(self, task_id, exec_time):
		print "do no error update"


def create_simulation(sim_type, sim_file, cpu, sim_count, deadline):
	if sim_type == "FIVE_ROOM":
		return FiveRoomSimulation(sim_file, cpu, sim_count, deadline)
	elif sim_type == "SUMO_TRAFFIC":
		return SumoTrafficSimulation(sim_file, cpu, sim_count, deadline)
	elif sim_type == "SUMO_OPTIMIZATION":
		return OptimizationSimulation(sim_file, cpu, sim_count, deadline)
	else:
		raise NotImplementedError('simulation type: ' + sim_type + ' not implemented')