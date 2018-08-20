#!/usr/bin/env python
# encoding: utf-8
import re
import json
import socket
import select
import logging

_LOGGER = logging.getLogger(__name__)

class AirCatData():
    """Class for handling the data retrieval."""

    def __init__(self, interval=1):
        """Initialize the data object."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.settimeout(1)
        self._socket.bind(('', 9000)) # aircat.phicomm.com
        self._socket.listen(5)
        self._rlist = [self._socket]
        self.devs = {}

    def shutdown(self):
        """Shutdown."""
        if self._socket  is not None:
            #_LOGGER.debug("Socket shutdown")
            self._socket.close()
            self._socket = None

    def loop(self):
        while True: self.update()

    def update(self, timeout=None): # None = wait forever, 0 = right now
        rfd,wfd,efd = select.select(self._rlist, [], [], timeout)
        for fd in rfd:
            try:
                if fd is self._socket:
                    conn, addr = self._socket.accept()
                    _LOGGER.debug('Connected %s', addr)
                    self._rlist.append(conn)
                    conn.settimeout(1)
                else:
                    self.handle(fd)
            except:
                import traceback
                _LOGGER.error('Exception: %s', traceback.format_exc())

    def handle(self, conn):
        """Handle connection."""
        data = conn.recv(1024) # If connection is closed, recv() will result a timeout exception and receive '' next time, so we can purge connection list
        if not data:
            _LOGGER.error('Closed %s', conn)
            self._rlist.remove(conn)
            conn.close()
            return

        if data.startswith(b'GET'):
            _LOGGER.debug('Request from HTTP -->\n%s', data)
            conn.sendall(b'HTTP/1.0 200 OK\nContent-Type: text/json\n\n' +
                json.dumps(self.devs, indent=2).encode('utf-8'))
            self._rlist.remove(conn)
            conn.close()
            return

        if len(data) < 34: # 23+5+6
            _LOGGER.error('Received Invalid %s', data)
            return

        address = data[17:23]
        mac = ''.join(['%02X' % (x if isinstance(x,int) else ord(x)) for x in address])
        jsonStr = re.findall(r"(\{.*?\})", str(data), re.M)
        count = len(jsonStr)
        if count > 0:
            status = json.loads(jsonStr[count - 1])
            self.devs[mac] = status
            _LOGGER.debug('Received %s: %s', mac, status)
        else:
            _LOGGER.debug('Received %s: %s',  mac, data)

        response = data[:23] + b'\x00\x18\x00\x00\x02{"type":5,"status":1}\xff#END#'
        #_LOGGER.debug('Response %s', response)
        conn.sendall(response)


if __name__ == '__main__':
    _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.addHandler(logging.StreamHandler())
    aircat = AirCatData()
    try:
        aircat.loop()
    except KeyboardInterrupt:
        pass
    aircat.shutdown()
    exit(0)


"""
Support for AirCat air sensor.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.aircat/
"""

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_NAME, CONF_DEVICES, CONF_SENSORS, TEMP_CELSIUS)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers import config_validation as cv

SENSOR_PM25 = 'value'
SENSOR_HCHO = 'hcho'
SENSOR_TEMPERATURE = 'temperature'
SENSOR_HUMIDITY = 'humidity'

DEFAULT_NAME = 'AirCat'
DEFAULT_SENSORS = [SENSOR_PM25, SENSOR_HCHO,
                   SENSOR_TEMPERATURE, SENSOR_HUMIDITY]

SENSOR_MAP = {
    SENSOR_PM25: ('PM2.5', 'μg/m³', 'blur'),
    SENSOR_HCHO: ('HCHO', 'mg/m³', 'biohazard'),
    SENSOR_TEMPERATURE: ('Temperature', TEMP_CELSIUS, 'thermometer'),
    SENSOR_HUMIDITY: ('Humidity', '%', 'water-percent')
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_DEVICES, default=['']):
        vol.All(cv.ensure_list, vol.Length(min=1)),
    vol.Optional(CONF_SENSORS, default=DEFAULT_SENSORS):
        vol.All(cv.ensure_list, vol.Length(min=1), [vol.In(SENSOR_MAP)]),
})

AIRCAT_SENSOR_THREAD = True # True: Thread mode, False: HomeAssistant update/poll mode

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the AirCat sensor."""
    name = config[CONF_NAME]
    devices = config[CONF_DEVICES]
    sensors = config[CONF_SENSORS]

    aircat = AirCatData()
    if AIRCAT_SENSOR_THREAD:
        import threading
        threading.Thread(target=aircat.loop).start()
    else:
        AirCatSensor.times = 0
        AirCatSensor.interval = len(sensors)

    result = []
    for index in range(len(devices)):
        for sensor_type in sensors:
            result.append(AirCatSensor(aircat,
                name + str(index + 1) if index else name,
                devices[index], sensor_type))
    add_devices(result)

class AirCatSensor(Entity):
    """Implementation of a AirCat sensor."""

    def __init__(self, aircat, name, mac, sensor_type):
        """Initialize the AirCat sensor."""
        sensor_name, unit, icon = SENSOR_MAP[sensor_type]
        self._name = name + ' ' + sensor_name
        self._mac = mac
        self._sensor_type = sensor_type
        self._unit = unit
        self._icon = 'mdi:' + icon
        self._aircat = aircat

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return self._icon

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return self._unit

    @property
    def available(self):
        """Return if the sensor data are available."""
        return self.attributes is not None

    @property
    def state(self):
        """Return the state of the device."""
        attributes = self.attributes
        if attributes is None:
            return None
        state = float(attributes[self._sensor_type])
        return state/1000 if self._sensor_type == SENSOR_HCHO else round(state)

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self.attributes if self._sensor_type == SENSOR_PM25 else None

    @property
    def attributes(self):
        """Return the attributes of the device."""
        if self._mac:
            return self._aircat.devs.get(self._mac)
        for mac in self._aircat.devs:
            return self._aircat.devs[mac]
        return None

    @property
    def should_poll(self):  # pylint: disable=no-self-use
        """No polling needed."""
        return not AIRCAT_SENSOR_THREAD

    def update(self):
        """Update state."""
        if AIRCAT_SENSOR_THREAD: # Dead code
            _LOGGER.error("Running in thread mode")
            return

        if AirCatSensor.times % AirCatSensor.interval == 0:
            _LOGGER.debug("Begin update %d: %s %s", AirCatSensor.times,
                self._mac, self._sensor_type)
            self._aircat.update()
            _LOGGER.debug("Ended update %d: %s %s", AirCatSensor.times,
                self._mac, self._sensor_type)
        AirCatSensor.times += 1

    def shutdown(self, event):
        """Signal shutdown."""
        #_LOGGER.debug('Shutdown')
        self._aircat.shutdown()