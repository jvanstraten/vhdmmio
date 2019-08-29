"""Submodule for custom field behavior VHDL code generation."""

from ...template import TemplateEngine
from ...core.behavior import CustomBehavior
from ..types import std_logic, std_logic_vector, Record, Array, gather_defs
from .base import BehaviorCodeGen, behavior_code_gen

@behavior_code_gen(CustomBehavior)
class CustomBehaviorCodeGen(BehaviorCodeGen):
    """Behavior code generator class for custom fields."""

    def generate(self):
        """Code generator implementation."""

        name = self.field_descriptor.name

        # Record the identifier strings that the templates can use in a
        # simplistic object, such that the templates can access the
        # identifiers using `<object>.<ident>`.
        class Identifiers: #pylint: disable=R0903
            """Storage object for VHDL identifiers."""
        identifiers = Identifiers()

        # Construct the external interfaces.
        for mode, name, count, typ in self.behavior.external_interfaces:
            setattr(identifiers, name, self.add_interface(mode, name, count, typ))

        # Register the internal interfaces.
        for internal, identifier in self.behavior.internal_interfaces:
            setattr(identifiers, internal.name, identifier)

        # Construct the state record, if the behavior is stateful.
        if self.behavior.state:
            state_name = 'f_%s_r' % name
            state_record = Record(state_name)
            for name, shape in self.behavior.state:
                if shape is not None:
                    state_record.append(name, std_logic_vector, shape)
                else:
                    state_record.append(name, std_logic)
            state_array = Array(state_name, state_record)
            state_decl, state_ob = state_array.make_variable(
                state_name, self.field_descriptor.width)
            for name, _ in self.behavior.state:
                setattr(identifiers, name, getattr(state_ob['$i$'], name))
            var_defs = gather_defs(state_array)
            var_defs.append(state_decl + ';')
        else:
            var_defs = []

        # Construct appropriately sized variables for data, strobe, and
        # subaddress. These can then be presented to the user template instead
        # of the slices generated downstream. If they were to be passed
        # directly, the user template wouldn't be able to slice again; you'd
        # get for instance r_hold(31 downto 16)(4) to get bit 20, which is not
        # legal in VHDL because reasons...
        if self.field_descriptor.base_bitrange.is_vector():
            var_defs.append(
                'variable f_%s_data: std_logic_vector(%d downto 0);' % (
                    name, self.field_descriptor.base_bitrange.width - 1))
            if self.behavior.bus.write is not None:
                var_defs.append(
                    'variable f_%s_strb: std_logic_vector(%d downto 0);' % (
                        name, self.field_descriptor.base_bitrange.width - 1))
        else:
            var_defs.append(
                'variable f_%s_data: std_logic;' % name)
            if self.behavior.bus.write is not None:
                var_defs.append(
                    'variable f_%s_strb: std_logic;' % name)
        # TODO: subaddress

        self.add_declarations(private='\n'.join(var_defs))

        def new_tple():
            tple = TemplateEngine()
            tple['i'] = '$i$'
            tple['s'] = identifiers
            return tple

        def expand(tple, block, ld='', sv=''):
            if block is not None:
                if ld:
                    block = '%s\n\n%s' % (ld, block)
                if sv:
                    block = '%s\n\n%s' % (block, sv)
                block = tple.apply_str_to_str(block, postprocess=False)
                if not block.strip():
                    block = None
            return block

        # Expand pre/post actions.
        tple = new_tple()
        pre = expand(tple, self.behavior.pre_access_template)
        post = expand(tple, self.behavior.post_access_template)
        if pre is not None or post is not None:
            self.add_interface_logic(pre, post)

        # Expand read actions.
        if self.behavior.bus.read is not None:
            ldsub = '' # TODO: subaddress
            lddat = '$data$ := $$r_data$$;\n'
            svdat = '$$r_data$$ := $data$;\n'

            tple = new_tple()
            tple['prot'] = 'r_prot'
            tple['addr'] = 'r_addr'
            tple['sub'] = 'f_%s_sub' % name
            if self.behavior.bus.read.deferring:
                tple['defer'] = 'r_defer'
            lookahead = expand(
                tple, self.behavior.read_lookahead_template,
                ld=ldsub)

            tple['data'] = 'f_%s_data' % name
            tple['ack'] = 'r_ack'
            tple['nack'] = 'r_nack'
            if self.behavior.bus.read.blocking:
                tple['block'] = 'r_block'
            normal = expand(
                tple, self.behavior.read_template,
                ld=lddat + ldsub, sv=svdat)

            tple['resp_ready'] = 'r_req'
            both = expand(
                tple, self.behavior.read_request_template,
                ld=lddat + ldsub, sv=svdat)

            if self.behavior.bus.read.deferring:
                tple = new_tple()
                tple['data'] = 'f_%s_data' % name
                tple['ack'] = 'r_ack'
                tple['nack'] = 'r_nack'
                if self.behavior.bus.read.blocking:
                    tple['block'] = 'r_block'
                deferred = expand(
                    tple, self.behavior.read_response_template,
                    ld=lddat, sv=svdat)
            else:
                deferred = None

            self.add_read_logic(normal, lookahead, both, deferred)

        # Expand write actions.
        if self.behavior.bus.write is not None:
            ldreq = ('$data$ := $$w_data$$;\n'
                     '$strb$ := $$w_strobe$$;\n') # TODO: subaddress

            tple = new_tple()
            tple['data'] = 'f_%s_data' % name
            tple['strb'] = 'f_%s_strb' % name
            tple['prot'] = 'w_prot'
            tple['addr'] = 'w_addr'
            tple['sub'] = 'f_%s_sub' % name
            if self.behavior.bus.write.deferring:
                tple['defer'] = 'w_defer'
            lookahead = expand(tple, self.behavior.write_lookahead_template, ld=ldreq)

            tple['ack'] = 'w_ack'
            tple['nack'] = 'w_nack'
            if self.behavior.bus.write.blocking:
                tple['block'] = 'w_block'
            normal = expand(tple, self.behavior.write_template, ld=ldreq)

            tple['resp_ready'] = 'w_req'
            both = expand(tple, self.behavior.write_request_template, ld=ldreq)

            if self.behavior.bus.write.deferring:
                tple = new_tple()
                tple['ack'] = 'w_ack'
                tple['nack'] = 'w_nack'
                if self.behavior.bus.write.blocking:
                    tple['block'] = 'w_block'
                deferred = expand(tple, self.behavior.write_response_template)
            else:
                deferred = None

            self.add_write_logic(normal, lookahead, both, deferred)
