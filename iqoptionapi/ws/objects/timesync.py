#=============================================================================#
#                             API BY: Lucas Code                              #    
#                     https://www.youtube.com/@lucascode                      #
#=============================================================================#
import time
import datetime
from iqoptionapi.ws.objects.base import Base


class TimeSync(Base):
    def __init__(self):
        super(TimeSync, self).__init__()
        self.__name = "timeSync"
        self.__server_timestamp = time.time()
        self.__expiration_time = 1

    @property
    def server_timestamp(self):
        while self.__server_timestamp==None:
            time.sleep(0.2)
            pass

        return self.__server_timestamp / 1000

    @server_timestamp.setter
    def server_timestamp(self, timestamp):
        self.__server_timestamp = timestamp

    @property
    def server_datetime(self):
        return datetime.datetime.fromtimestamp(self.server_timestamp)

    @property
    def expiration_time(self):
        return self.__expiration_time

    @expiration_time.setter
    def expiration_time(self, minutes):
        self.__expiration_time = minutes

    @property
    def expiration_datetime(self):
        return self.server_datetime + datetime.timedelta(minutes=self.expiration_time)

    @property
    def expiration_timestamp(self):
        return time.mktime(self.expiration_datetime.timetuple())
