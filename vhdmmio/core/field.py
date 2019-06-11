"""Module for `Field`, `FieldDescriptor`, and `FieldLogic` objects."""

from .metadata import Metadata, ExpandedMetadata
from .bitrange import BitRange
from .register import Register
from .accesscaps import ReadWriteCapabilities

class FieldDescriptor:
    """Class representing the description of a field or an array of fields, as
    described in a single node of the YAML file."""

    def __init__(self, regfile, **kwargs):
        """Constructs a field descriptor from its YAML dictionary
        representation."""
        self._regfile = regfile

        # Parse address.
        address = kwargs.pop('address', None)
        if isinstance(address, list):
            self._field_repeat = None
            self._stride = None
            self._field_stride = None
            self._bitranges = [BitRange.from_spec(regfile.bus_width, spec) for spec in address]
            if not self._bitranges:
                raise ValueError('at least one address must be specified')
            if 'repeat' in kwargs:
                raise ValueError('cannot combine repeat with multiple addresses')
            if 'field_repeat' in kwargs:
                raise ValueError('cannot combine field-repeat with multiple addresses')
            if 'stride' in kwargs:
                raise ValueError('cannot combine stride with multiple addresses')
            if 'field_stride' in kwargs:
                raise ValueError('cannot combine field-stride with multiple addresses')

        elif isinstance(address, (str, int)):
            base = BitRange.from_spec(regfile.bus_width, address)
            repeat = int(kwargs.pop('repeat', 1))
            if repeat < 1:
                raise ValueError('repeat must be positive')
            field_repeat = kwargs.pop('field_repeat', None)
            if field_repeat is None:
                field_repeat = repeat
            else:
                field_repeat = int(field_repeat)
            if field_repeat < 1:
                raise ValueError('field-repeat must be positive')
            stride = int(kwargs.pop('stride', 2**base.size))
            if stride < 2**base.size:
                raise ValueError('stride is smaller than the block size')
            if stride & (2**base.size-1):
                raise ValueError('stride is not aligned to the block size')
            field_stride = int(kwargs.pop('field_stride', 2**base.width))
            if field_stride < base.width:
                raise ValueError('field-stride is smaller than the width of a single field')

            self._field_repeat = field_repeat
            self._stride = stride
            self._field_stride = field_stride
            self._bitranges = [base.move(
                (index // field_repeat) * stride,
                (index % field_repeat) * field_stride)
                               for index in range(repeat)]

        else:
            raise ValueError('invalid or missing address')

        # Parse metadata.
        self._meta = Metadata.from_dict(len(self._bitranges), kwargs)
        if any(('register_' + key in kwargs for key in ('mnemonic', 'name', 'brief', 'doc'))):
            self._reg_meta = Metadata.from_dict(len(self._bitranges), kwargs, 'register_')
        else:
            self._reg_meta = None

        # Parse type information.
        self._logic = FieldLogic.from_dict(kwargs)

        # Collect the fields described by this descriptor.
        self._fields = tuple((
            Field(self._meta[index], bitrange, self._logic, self, index)
            for index, bitrange in enumerate(self._bitranges)))

        # Check for unknown keys.
        for key in kwargs:
            raise ValueError('unexpected key in field description: %s' % key)

    @classmethod
    def from_dict(cls, regfile, dictionary):
        """Constructs a field descriptor object from a dictionary."""
        for key in list(dictionary.keys()):
            if '-' in key:
                dictionary[key.replace('-', '_')] = dictionary.pop(key)
        return cls(regfile, **dictionary)

    def to_dict(self, dictionary=None):
        """Returns a dictionary representation of this object."""
        if dictionary is None:
            dictionary = {}

        # Write address.
        base = self._bitranges[0]
        if len(self._bitranges) == 1:
            dictionary['address'] = base.to_spec()
        if self._field_repeat is None:
            dictionary['address'] = [address.to_spect() for address in self._bitranges]
        else:
            dictionary['address'] = base.to_spec()
            dictionary['repeat'] = len(self._bitranges)
            if self._field_repeat != len(self._bitranges):
                dictionary['field-repeat'] = self._field_repeat
            if self._stride != 2**base.size:
                dictionary['stride'] = self._stride
            if self._field_stride != base.width:
                dictionary['field-stride'] = self._field_stride

        # Write metadata.
        self._meta.to_dict(dictionary)
        if self._reg_meta is not None:
            self._reg_meta.to_dict(dictionary, 'register-')

        # Write type information.
        self._logic.to_dict(dictionary)

        return dictionary

    @property
    def meta(self):
        """Metadata for this group of fields."""
        return self._meta

    @property
    def reg_meta(self):
        """Metadata for the surrounding register, if any."""
        return self._reg_meta

    @property
    def logic(self):
        """Object logic description."""
        return self._logic

    @property
    def regfile(self):
        """Register file that this field is bound to."""
        return self._regfile

    @property
    def fields(self):
        """Collection of fields described by this descriptor."""
        return self._fields

class Field:
    """Represents a single field."""

    def __init__(self, meta, bitrange, logic, descriptor, index, register=None):
        """Constructs a new field.

         - `meta` is the expanded metadata/documentation for this field.
         - `bitrange` is the address of the field.
         - `logic` points to an object deriving from `FieldLogic`, describing
           the logic needed to construct the field in hardware.
         - `descriptor` points to the `FieldDescriptor` that describes this
           field.
         - `index` is the index of this field within the parent `FieldDescriptor`.
         - `register`, if specified, points to the `Register` that contains this
           field. If not specified, it can be assigned later.
        """
        super().__init__()

        if not isinstance(meta, ExpandedMetadata):
            raise TypeError('meta must be of type ExpandedMetadata')
        self._meta = meta

        if not isinstance(bitrange, BitRange):
            raise TypeError('bitrange must be of type BitRange')
        self._bitrange = bitrange

        if not isinstance(logic, FieldLogic):
            raise TypeError('logic must be of type FieldLogic')
        self._logic = logic

        if not isinstance(descriptor, FieldDescriptor):
            raise TypeError('descriptor must be of type FieldDescriptor')
        self._descriptor = descriptor
        if index is None:
            self._index = None
        else:
            self._index = int(index)

        if register is not None and not isinstance(register, Register):
            raise TypeError('register must be None or be of type Register')
        self._register = register

    @property
    def meta(self):
        """Field metadata."""
        return self._meta

    @property
    def bitrange(self):
        """Field address and bitrange."""
        return self._bitrange

    @property
    def logic(self):
        """Field logic descriptor."""
        return self._logic

    @property
    def descriptor(self):
        """Field descriptor."""
        return self._descriptor

    @property
    def index(self):
        """Field index within an array of fields, if any."""
        return self._index

    @property
    def register(self):
        """The register associated to this field, or `None` if it has not been
        mapped to a register yet."""
        if self._register is None:
            raise ValueError('this field does not a register assigned to it yet')
        return self._register

    @register.setter
    def register(self, register):
        if not isinstance(register, Register):
            raise TypeError('register must be of type Register')
        if self._register is not None:
            raise ValueError('this field already has a register assigned to it')
        self._register = register

    def is_array(self):
        """Returns whether this field is a scalar or an array. Fields are
        implicitly arrays when they have two or more entries and scalar when
        there is only one."""
        return len(self.descriptor) > 1

    def __str__(self):
        return self.meta.name

class field_logic:
    """Decorator for child classes of `FieldLogic` that ensures that they're
    registered correctly."""
    #pylint: disable=C0103,W0212,R0903
    def __init__(self, typ):
        super().__init__()
        assert isinstance(typ, str)
        self._typ = typ

    def __call__(self, cls):
        assert issubclass(cls, FieldLogic)
        assert self._typ not in FieldLogic._TYPE_LOOKUP
        FieldLogic._TYPE_LOOKUP[self._typ] = cls
        cls._TYPE_CODE = self._typ
        return cls

class FieldLogic(ReadWriteCapabilities):
    """Base class for representing the hardware description of this register
    and its interface to the user's logic."""

    _TYPE_CODE = None
    _TYPE_LOOKUP = {}

    @staticmethod
    def from_dict(dictionary):
        """Constructs a `FieldLogic` object from a dictionary. The key `'type'`
        is used to select the subclass to use."""
        import vhdmmio.core.logic
        typ = dictionary.pop('type', 'control')
        cls = FieldLogic._TYPE_LOOKUP.get(typ, None)
        if cls is None:
            raise ValueError('unknown type code "%s"' % typ)
        return cls(dictionary)

    def to_dict(self, dictionary):
        """Returns a dictionary representation of this object."""
        dictionary['type'] = self.type_code

    @property
    def type_code(self):
        """Returns the type code of this field."""
        return self._TYPE_CODE
