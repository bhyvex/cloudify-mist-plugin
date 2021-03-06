from cloudify import ctx
from cloudify.decorators import operation
from cloudify.exceptions import NonRecoverableError, RecoverableError
from mistclient import MistClient
from time import sleep
import connection
import constants
import keypair
import os
import string
import random


@operation
def creation_validation(**_):
    """ This checks that all user supplied info is valid """
    ctx.logger.info('Checking validity of info')
    mist_client = connection.MistConnectionClient()
    try:
        client = mist_client.client
    except:
        raise NonRecoverableError('Credentials failed')

    for property_key in constants.INSTANCE_REQUIRED_PROPERTIES:
        if property_key not in ctx.node.properties:
            raise NonRecoverableError(
                '{0} is a required input. Unable to create.'.format(property_key))
    cloud = client.clouds(id=ctx.node.properties['cloud_id'])
    if not len(cloud):
        raise NonRecoverableError(
            '{0} cloud was not found.'.format(ctx.node.properties['cloud_id']))
    image = ""
    for im in cloud[0].images:
        if im[id] == ctx.node.properties['image_id']:
            image = im
            break
    if not image:
        raise NonRecoverableError(
            'image_id {0} not found.'.format(ctx.node.properties['image_id']))
    size = ""
    for si in cloud[0].sizes:
        if si[id] == ctx.node.properties['size_id']:
            size = si
            break
    if not size:
        raise NonRecoverableError(
            'size_id {0} not found.'.format(ctx.node.properties['size_id']))
    location = ""
    for lo in cloud[0].locations:
        if lo[id] == ctx.node.properties['location_id']:
            location = lo
            break
    if not location:
        raise NonRecoverableError(
            'location_id {0} not found.'.format(ctx.node.properties['location_id']))

    machines = cloud[0].machines(search=ctx.node.properties["name"])
    if ctx.node.properties['use_external_resource'] and not len(machines):
        raise NonRecoverableError(
            'machine {0} not found.'.format(ctx.node.properties["name"]))
    if not ctx.node.properties['use_external_resource'] and len(machines):
        raise NonRecoverableError(
            'machine {0} exists.'.format(ctx.node.properties["name"]))
    if ctx.node.properties['use_external_resource'] and len(machines):
        if machines[0].info["state"] == "running":
            pass
        elif machines[0].info["state"] == "stopped":
            try:
                machines[0].start()
            except:
                pass
            delay = 0
            while True:
                sleep(10)
                cloud[0].update_machines()
                if cloud[0].machines(search=ctx.node.properties["name"])[0].info["state"] == "running":
                    break
                elif delay == 5:
                    raise NonRecoverableError(
                        'machine {0} in stopped state.'.format(ctx.node.properties["name"]))
                delay += 1
        else:
            raise NonRecoverableError(
                'machine {0} error state.'.format(ctx.node.properties["name"]))


@operation
def create(**_):
    mist_client = connection.MistConnectionClient()
    try:
        client = mist_client.client
    except:
        raise NonRecoverableError('Credentials failed')
    cloud = client.clouds(id=ctx.node.properties['parameters']['cloud_id'])[0]
    params = ctx.node.properties['parameters']
    if ctx.node.properties['use_external_resource']:
        machine = mist_client.machine
        ctx.instance.runtime_properties["info"] = machine.info
        if len(machine.info["public_ips"]):
            ctx.instance.runtime_properties["ip"] = machine.info["public_ips"][0]
            ctx.instance.runtime_properties["networks"] = machine.info["public_ips"]
            ctx.instance.runtime_properties["mist_type"] = "machine"

        return
    try:
        del params['cloud_id']
        name = params.pop('name')
        key = params.pop('key')
        image_id = params.pop('image_id')
        location_id = params.pop('location_id')
        size_id = params.pop('size_id')
        job = cloud.create_machine(name, key, image_id, location_id, size_id,
                                   async=True, verbose=True,
                                   fire_and_forget=False, **params)
        params['name'] = name
        params['key'] = key
        params['image_id'] = image_id
        params['location_id'] = location_id
        params['size_id'] = size_id
        for log in job["logs"]:
            if log["action"] == 'machine_creation_finished':
                ctx.instance.runtime_properties["machine_id"] = log["machine_id"]
                break
    except Exception as exc:
        raise NonRecoverableError(exc)
    machine_id = ctx.instance.runtime_properties['machine_id'] or \
                ctx.node.properties['resource_id']
    cloud.update_machines()
    machine = cloud.machines(id=machine_id)[0]
    ctx.instance.runtime_properties["info"] = machine.info
    if len(machine.info["public_ips"]):
        ctx.instance.runtime_properties["ip"] = machine.info["public_ips"][0]
    ctx.instance.runtime_properties["networks"] = machine.info["public_ips"]
    ctx.instance.runtime_properties["mist_type"] = "machine"
    ctx.logger.info('Machine created')


@operation
def start(**_):
    try:
        connection.MistConnectionClient().machine.start()
    except Exception as exc:
        ctx.logger.error("Failed to start machine. Already running?")
    if ctx.node.properties.get("monitoring"):
        connection.MistConnectionClient().machine.enable_monitoring()
        ctx.logger.info('Monitoring enabled')


@operation
def stop(**_):
    try:
        connection.MistConnectionClient().machine.stop()
        ctx.logger.info('Machine stopped')
    except Exception as exc:
        ctx.logger.error("Failed to stop machine")
        raise Exception(exc)


@operation
def delete(**_):
    try:
        connection.MistConnectionClient().machine.destroy()
    except Exception as exc:
        raise Exception(exc)


@operation
def run_script(**kwargs):
    client = connection.MistConnectionClient().client
    machine = connection.MistConnectionClient().machine
    script_params = kwargs.get("params", "")
    if kwargs.get("script_id", ''):
        try:
            job_id = machine.run_script(**kwargs)
        except Exception as exc:
            raise NonRecoverableError(exc)
    else:
        try:
            response = client.add_and_run_script(machine.cloud.id, machine.id,
                                                 script_params=script_params,
                                                 fire_and_forget=False,
                                                 **kwargs)
        except Exception as exc:
            raise NonRecoverableError(exc)
