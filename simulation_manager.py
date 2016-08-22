import time, datetime

from threading import Thread,Condition
import logging, threading, thread 
from simulation import create_simulation
from dto.model import ResourceAllocationInput
from dddas_exception import NoCapacityException, DeadlineMissedException
from constants import *

host_log = open("./output/host_" + str(datetime.datetime.now()), "wb")

SCHEDULE_FOUND = False

def write_result(simulation, input_name=None):
	if input_name  == None:
		file_name = './output/' + simulation.getName()
	else:
		file_name = './output/' + input_name

	fo = open(file_name, "wb")
	fo.write( 'total tasks : ' +  str(simulation.number_of_sims) + '\n' )
	fo.write( 'state: ' +  str(simulation.state) + '\n' )
	if simulation.state == SIMULATION_STATE_FAILED:
		fo.write( 'failure time: ' +  str(simulation.failure_time) + '\n' )
	fo.write( 'average error: ' +  str(simulation.error) + '\n' )
	fo.write( 'start time: ' +  str(simulation.creation_time) + '\n' )
	fo.write( 'schedule time: ' +  str(simulation.schedule_time) + '\n' )
	fo.write( 'deadline: ' +  str(simulation.deadline) + '\n' )
	if (hasattr(simulation, 'ending_time')): 
		fo.write( 'end time: ' +  str(simulation.ending_time) + '\n' )
	fo.write( 'remaining tasks ' +  str(simulation.remaining_number_of_sims) + '\n' )
	fo.write( 'sim_id, start time, est exec duration, host, actual duration, response time, response duration, end time \n' )

	for key, instance in simulation.tasks.iteritems():
		fo.write( str(instance.id) + ', ' )
		if (hasattr(instance, 'start_time')): 
			fo.write( str(instance.start_time) + ', ' )
			fo.write( str(instance.exec_time) + ', ' )
			fo.write( str(instance.hostname) + ', ' )
		else:
			fo.write( ', , , ')
		if (hasattr(instance, 'actual_duration')): 
			fo.write( str(instance.actual_duration) + ', '  )
		if (hasattr(instance, 'response_time')): 
			fo.write( str(instance.response_time) + ', '  )
		if (hasattr(instance, 'finish_duration')): 
			fo.write( str(instance.finish_duration)+ ', ' )
		else:
			fo.write( ', , , ')
		if (hasattr(instance, 'end_time')): 
			fo.write( str(instance.end_time)  )
		fo.write( '\n' )
	# Close opend file
	fo.close()



# class 
class SimulationManager(object):

	def __init__(self, valid_simulations, policy, sim_service_freq, sim_status_update_freq, resource_manager):
		logging.info('valid sims: ' +  valid_simulations);
		self.valid_sims = valid_simulations.split(',')
		self.allocation_policy = policy
		self.resource_manager = resource_manager
		self.simulations = {}
		#self.simulationService = SimulationService(self, sim_service_freq)
		#self.simulationService.start()
		# not using it anymore
		#self.statusUpdateService = StatusUpdateService(self, sim_status_update_freq)
		#self.statusUpdateService.start()
		
	def logRes(self, sim_name, slot_name, host, active_task_id, remaining_count):
		self.getSimulation(sim_name).fo.write(str(datetime.datetime.now()) + ',' + 
				host + ',' + slot_name + ',' + str(active_task_id) + ',' + str(remaining_count) + '\n')


	def logHostRes(self, sim_name, hostname, container_count):
		sim = self.getSimulation(sim_name)
		host_log.write(str(datetime.datetime.now()) + ',' + hostname + ',' + 
				str(container_count) + ',' + str(sim.error) + ',' + str(sim.remaining_number_of_sims) + '\n')
		host_log.flush()
		
	def logtotal(self, sim_name, container_count):
		sim = self.getSimulation(sim_name)
		sim.to.write(str(datetime.datetime.now()) + ',' + str(container_count) + ',' + str(sim.error) + '\n')
		sim.to.flush()


	def logFlush(self, sim_name):
		self.getSimulation(sim_name).fo.write('\n')
		self.getSimulation(sim_name).fo.flush()
	
	def getSimulation(self, sim_name):
		return self.simulations.get(sim_name)
	
	def createSimulation(self, sim_type, sim_config_file, cpu, sim_count, deadline):
		sim_object = create_simulation(sim_type, sim_config_file, cpu, sim_count, deadline)
		name = sim_object.getName()
		self.simulations[name] = sim_object
		return sim_object
	
	def determineRequiredResources(self, sim_name):
		# keep on looping till all the simulations are started
		logging.info('determining required resources...')
		resource_allocation_input = ResourceAllocationInput()
		sim_object = self.simulations.get(sim_name)
		resource_allocation_input.sim_name = sim_name
		resource_allocation_input.deadline = sim_object.deadline
		resource_allocation_input.margin = sim_object.margin
		resource_allocation_input.margin_value = sim_object.margin_value
		tasks = {}
		logging.info('number of tasks: ' + str(len(sim_object.getTasks())))
		for task_id, task in sim_object.getTasks().iteritems():
                        if task.status == SIMULATION_STATE_SCHEDULED:
                                tasks[task_id] = task
		if len(tasks) == 0:
			logging.info('Simulation: ' + sim_name + ' has finished!!!!');
			return None
		resource_allocation_input.tasks = tasks
		container_slots = self.resource_manager.getAssignedContainers(sim_name)
		return self.allocation_policy.determineResources(resource_allocation_input, container_slots)
	
	def startSimulation(self, sim_name, container_slot_count):
		logging.debug('self.valid_sims: ' + str(self.valid_sims))
		sim = self.simulations.get(sim_name)		
		logging.debug('simulation: ' + str(sim))
		if sim.sim_type not in self.valid_sims:
			logging.error('Not a valid simulation type')
			return
		#self.resource_manager.allocateResources(sim_name, sim.getResourceSize(), sim.getDeadline(), container_slot_count, self)
		logging.info('Scheduling simulation: ' + sim_name + '...')
		sim.scheduleSimulation()
		self.resource_manager.scheduleSimulationAllTasks(sim, self)
		logging.info(sim.getName() + ' simulation been scheduled ...')

	def activateTask(self, sim_name, task_id, host, start_time):
		logging.info('Marking sim: ' + sim_name + ' and task id: ' + str(task_id) + ' as started...')
		sim = self.simulations.get(sim_name)
		tasks = sim.getTasks()
		task = tasks.get(task_id)
		# for book keeping
		if task.status != SIMULATION_STATE_SCHEDULED:
			return False
		task.status = SIMULATION_STATE_ACTIVE
		task.start_time = start_time
		task.hostname = host
		return True 

	def finishSimulation(self, sim_name):
		sim = self.simulations.get(sim_name)
		tasks = sim.getTasks()
		for taskname, task in tasks.iteritems():
			if (not hasattr(task, 'response_time')) and (sim.finish_count <= 5):
				logging.info('Task ' + str(taskname) + ' is pending tasks, will not finish yet for sim: ' + sim_name)
				sim.finish_count = sim.finish_count + 1
				return False
		sim.endSimulation()
		logging.warn('SIMULATION FINISHED ............')
		self.resource_manager.freeSimulation(sim_name, sim.getResourceSize())
		return True
		
	def markRunningTask(self, sim_name, task_id):
		tasks = self.simulations.get(sim_name).getTasks()
		task = tasks.get(task_id)
		task.status = SIMULATION_STATE_RUNNING
		task.schedule_time = datetime.datetime.now()

	def logSimTaskEnd(self, sim_name, task_id, response_time):
		sim = self.simulations.get(sim_name)
		if sim is None:
			return "Simulation not found"
		tasks = sim.getTasks()
		task = tasks.get(task_id)
		task.response_time = response_time
		diff = (task.response_time - task.start_time)

		logging.info('logging response for ' + sim_name + ' and task id ' + str(task_id) +  ' total dur ' + str(diff));
		task.finish_duration = diff.total_seconds() * 1000
		logging.debug(str(task.finish_duration))
		sim.updateRunTimeError(task_id, task.finish_duration)
		sim.decrementRemainingCount()

	def finishAndScheduleSimTask(self, sim_name, task_id, duration, result):
		logging.info('received response for ' + sim_name + ' and task id ' + str(task_id) + ' having duration ' + str(duration));
		sim = self.simulations.get(sim_name)
		logging.info('found sim'  + str(sim))
		if sim is None:
			return "Simulation not found"
		tasks = sim.getTasks()
		task = tasks.get(task_id)
		task.status = SIMULATION_STATE_FINISHED
		sim.state = SIMULATION_STATE_SCHEDULED

		task.actual_duration = duration
		new_task = sim.createTask(task_id, result)
		logging.info('scheduling next task for id.. '  + str(new_task.id))
		self.resource_manager.scheduleNextSimTask(self, task.hostname, sim, task_id, new_task)
		return "Success"
		

	def updateSimulationExecutionTime(self, sim_name):
		sim = self.simulations.get(sim_name)
		sim.updateEstimatedExecutionTime()
	
	def finishSimTask(self, sim_name, task_id):	
		
		sim = self.simulations.get(sim_name)		
		tasks = sim.getTasks()
		task = tasks.get(task_id)
		task.end_time = datetime.datetime.now()
		task.status = SIMULATION_STATE_FINISHED
		sim.state = SIMULATION_STATE_SCHEDULED
		

