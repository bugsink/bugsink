import json


class VolumeBasedCondition(object):

    def __init__(self, period, nr_of_periods, volume):
        self.period = period
        self.nr_of_periods = nr_of_periods
        self.volume = volume

    @classmethod
    def from_json_str(cls, json_str):  # TODO had toch gewoon dict moeten wezen
        json_dict = json.loads(json_str)
        return VolumeBasedCondition(
            json_dict['period'],
            json_dict['nr_of_periods'],
            json_dict['volume'],
        )

    def to_json_str(obj):
        return json.dumps(obj.__dict__)

    def __eq__(self, other):
        return self.__dict__ == other.__dict__
