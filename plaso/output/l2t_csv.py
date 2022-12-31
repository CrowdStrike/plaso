# -*- coding: utf-8 -*-
"""Output module for the log2timeline (L2T) CSV format.

For documentation on the L2T CSV format see:
https://forensics.wiki/l2t_csv
"""

import datetime
import pytz

from dfdatetime import interface as dfdatetime_interface
from dfdatetime import posix_time as dfdatetime_posix_time

from plaso.containers import interface as containers_interface
from plaso.lib import definitions
from plaso.lib import errors
from plaso.output import formatting_helper
from plaso.output import interface
from plaso.output import logger
from plaso.output import manager
from plaso.output import shared_dsv


class L2TCSVEventFormattingHelper(shared_dsv.DSVEventFormattingHelper):
  """L2T CSV output module event formatting helper."""

  def GetFormattedMACBGroup(self, output_mediator, macb_group):
    """Retrieves a string representation of a MACB group.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      macb_group (list[dict[str, str]]): group of output field values per name
          with identical timestamps, attributes and values.

    Returns:
      str: string representation of the MACB group.
    """
    timestamp_descriptions = [
        field_values.get('type', None) for field_values in macb_group]

    field_values = []
    for field_name in self._field_names:
      if field_name == 'MACB':
        field_value = output_mediator.GetMACBRepresentationFromDescriptions(
            timestamp_descriptions)

      elif field_name == 'type':
        field_value = '; '.join(timestamp_descriptions)

      else:
        field_value = macb_group[0].get(field_name, None)

      field_values.append(field_value)

    return self.field_delimiter.join(field_values)


class L2TCSVFieldFormattingHelper(formatting_helper.FieldFormattingHelper):
  """L2T CSV output module field formatting helper."""

  # Maps the name of a fields to a a callback function that formats
  # the field value.
  _FIELD_FORMAT_CALLBACKS = {
      'date': '_FormatDate',
      'desc': '_FormatMessage',
      'extra': '_FormatExtraAttributes',
      'filename': '_FormatDisplayName',
      'format': '_FormatParser',
      'host': '_FormatHostname',
      'inode': '_FormatInode',
      'MACB': '_FormatMACB',
      'notes': '_FormatTag',
      'short': '_FormatMessageShort',
      'source': '_FormatSourceShort',
      'sourcetype': '_FormatSource',
      'time': '_FormatTime',
      'timezone': '_FormatTimeZone',
      'type': '_FormatType',
      'user': '_FormatUsername',
      'version': '_FormatVersion'}

  # The field format callback methods require specific arguments hence
  # the check for unused arguments is disabled here.
  # pylint: disable=unused-argument

  def _FormatDate(self, output_mediator, event, event_data, event_data_stream):
    """Formats a date field.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      event (EventObject): event.
      event_data (EventData): event data.
      event_data_stream (EventDataStream): event data stream.

    Returns:
      str: date formatted as "MM/DD/YYYY" or "00/00/0000" on error.
    """
    # For now check if event.timestamp is set, to mimic existing behavior of
    # using 00/00/0000 for 0 timestamp values.
    if not event.timestamp:
      return '00/00/0000'

    date_time = event.date_time
    if not date_time or date_time.is_local_time:
      date_time = dfdatetime_posix_time.PosixTimeInMicroseconds(
          timestamp=event.timestamp)

    # Note that GetDateWithTimeOfDay will return the date and time in UTC,
    # so no adjustment for date_time.time_zone_offset is needed.
    year, month, day_of_month, hours, minutes, seconds = (
        date_time.GetDateWithTimeOfDay())

    if output_mediator.timezone != pytz.UTC:
      try:
        datetime_object = datetime.datetime(
            year, month, day_of_month, hours, minutes, seconds,
            tzinfo=pytz.UTC)

        datetime_object = datetime_object.astimezone(output_mediator.timezone)

        year = datetime_object.year
        month = datetime_object.month
        day_of_month = datetime_object.day

      except (OSError, OverflowError, TypeError, ValueError):
        year, month, day_of_month = (None, None, None)

    if None in (year, month, day_of_month):
      self._ReportEventError(event, event_data, (
          'unable to copy timestamp: {0!s} to a human readable date. '
          'Defaulting to: "00/00/0000"').format(event.timestamp))
      return '00/00/0000'

    return '{0:02d}/{1:02d}/{2:04d}'.format(month, day_of_month, year)

  def _FormatExtraAttributes(
      self, output_mediator, event, event_data, event_data_stream):
    """Formats an extra attributes field.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      event (EventObject): event.
      event_data (EventData): event data.
      event_data_stream (EventDataStream): event data stream.

    Returns:
      str: extra attributes field.

    Raises:
      NoFormatterFound: if no event formatter can be found to match the data
          type in the event data.
    """
    message_formatter = output_mediator.GetMessageFormatter(
        event_data.data_type)
    if not message_formatter:
      raise errors.NoFormatterFound((
          'Unable to find message formatter event with data type: '
          '{0:s}.').format(event_data.data_type))

    formatted_attribute_names = (
        message_formatter.GetFormatStringAttributeNames())
    formatted_attribute_names.update(definitions.RESERVED_VARIABLE_NAMES)

    extra_attributes = []
    for attribute_name, attribute_value in event_data.GetAttributes():
      if attribute_name in formatted_attribute_names:
        continue

      # Ignore attribute container identifier and date and time values.
      if isinstance(attribute_value, (
          containers_interface.AttributeContainerIdentifier,
          dfdatetime_interface.DateTimeValues)):
        continue

      if (isinstance(attribute_value, list) and attribute_value and
          isinstance(attribute_value[0],
                     dfdatetime_interface.DateTimeValues)):
        continue

      # Some parsers have written bytes values to storage.
      if isinstance(attribute_value, bytes):
        attribute_value = attribute_value.decode('utf-8', 'replace')
        logger.warning(
            'Found bytes value for attribute "{0:s}" for data type: '
            '{1!s}. Value was converted to UTF-8: "{2:s}"'.format(
                attribute_name, event_data.data_type, attribute_value))

      # With ! in {1!s} we force a string conversion since some of
      # the extra attributes values can be integer, float point or
      # boolean values.
      extra_attributes.append('{0:s}: {1!s}'.format(
          attribute_name, attribute_value))

    if event_data_stream:
      for attribute_name, attribute_value in event_data_stream.GetAttributes():
        if attribute_name != 'path_spec':
          extra_attributes.append('{0:s}: {1!s}'.format(
              attribute_name, attribute_value))

    extra_attributes = '; '.join(sorted(extra_attributes))

    return extra_attributes.replace('\n', '-').replace('\r', '')

  def _FormatParser(
      self, output_mediator, event, event_data, event_data_stream):
    """Formats a parser field.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      event (EventObject): event.
      event_data (EventData): event data.
      event_data_stream (EventDataStream): event data stream.

    Returns:
      str: parser field.
    """
    return getattr(event_data, 'parser', '-')

  def _FormatType(self, output_mediator, event, event_data, event_data_stream):
    """Formats a type field.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      event (EventObject): event.
      event_data (EventData): event data.
      event_data_stream (EventDataStream): event data stream.

    Returns:
      str: type field.
    """
    return getattr(event, 'timestamp_desc', '-')

  def _FormatVersion(
      self, output_mediator, event, event_data, event_data_stream):
    """Formats a version field.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      event (EventObject): event.
      event_data (EventData): event data.
      event_data_stream (EventDataStream): event data stream.

    Returns:
      str: version field.
    """
    return '2'

  # pylint: enable=unused-argument


class L2TCSVOutputModule(interface.TextFileOutputModule):
  """CSV format used by log2timeline, with 17 fixed fields."""

  NAME = 'l2tcsv'
  DESCRIPTION = 'CSV format used by legacy log2timeline, with 17 fixed fields.'

  _FIELD_NAMES = [
      'date', 'time', 'timezone', 'MACB', 'source', 'sourcetype', 'type',
      'user', 'host', 'short', 'desc', 'version', 'filename', 'inode', 'notes',
      'format', 'extra']

  def __init__(self):
    """Initializes an output module."""
    field_formatting_helper = L2TCSVFieldFormattingHelper()
    event_formatting_helper = L2TCSVEventFormattingHelper(
        field_formatting_helper, self._FIELD_NAMES)
    super(L2TCSVOutputModule, self).__init__(event_formatting_helper)

  def WriteFieldValues(self, output_mediator, field_values):
    """Writes field values to the output.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      field_values (dict[str, str]): output field values per name.
    """
    output_text = self._event_formatting_helper.field_delimiter.join(
        field_values.values())

    self.WriteLine(output_text)

  def WriteFieldValuesOfMACBGroup(self, output_mediator, macb_group):
    """Writes field values of a MACB group to the output.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
      macb_group (list[dict[str, str]]): group of output field values per name
          with identical timestamps, attributes and values.
    """
    output_text = self._event_formatting_helper.GetFormattedMACBGroup(
        output_mediator, macb_group)

    self.WriteLine(output_text)

  def WriteHeader(self, output_mediator):
    """Writes the header to the output.

    Args:
      output_mediator (OutputMediator): mediates interactions between output
          modules and other components, such as storage and dfVFS.
    """
    output_text = self._event_formatting_helper.GetFormattedFieldNames()
    self.WriteLine(output_text)


manager.OutputManager.RegisterOutput(L2TCSVOutputModule)
