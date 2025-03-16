import logging


class TlvParser:

    class TagTrait:
        UniversalClass = 1 << 0
        ApplicationClass = 1 << 1
        ContextSpecificClass = 1 << 2
        PrivateClass = 1 << 3
        PrimitiveDataObject = 1 << 4
        ConstructedDataObject = 1 << 5

    @staticmethod
    def are_all_bits_set(byte_value, bit_positions):
        return all((byte_value & (1 << bit)) != 0 for bit in bit_positions)

    @staticmethod
    def is_bit_set(byte_value, bit_position):
        return (byte_value & (1 << bit_position)) != 0

    @staticmethod
    def calculate_tlv_tag(data, offset):
        if len(data) < offset + 1:
            logging.warning(f'TlvParser: expected len: {offset + 1} but {len(data)}!')
            return 0x0

        byte_value = data[offset]
        offset += 1
        is_tag_num_in_next_byte = TlvParser.are_all_bits_set(byte_value, [0, 1, 2, 3, 4])
        if not is_tag_num_in_next_byte:
            return byte_value

        tag_value = byte_value

        i = 0
        while is_tag_num_in_next_byte:
            tag_value = (tag_value << 8)
            byte_value = data[offset]
            offset += 1
            is_tag_num_in_next_byte = TlvParser.is_bit_set(byte_value, 7)
            i += 1
            if i > 7:
                logging.warning(f'TlvParser: tag_value is too big!')
                return tag_value

        return tag_value, offset

    @staticmethod
    def calculate_tlv_length(data, offset):
        if not data or len(data) == offset:
            return 0, offset

        b0 = data[offset]
        offset += 1
        if b0 < 0x80:
            return b0, offset

        if b0 == 0x81:
            res = data[offset]
            offset += 1
            return res, offset

        if b0 == 0x82:
            hb = data[offset]
            offset += 1
            lb = data[offset]
            offset += 1
            res = (hb << 8) + lb
            return res, offset

        return 0, offset

    @staticmethod
    def has_trait(tag, trait):
        def get_most_significant_byte(value):
            return (value >> 56) & 0xFF

        upper = get_most_significant_byte(tag)

        b7 = TlvParser.is_bit_set(upper, 7)
        b6 = TlvParser.is_bit_set(upper, 6)

        if trait == TlvParser.TagTrait.UniversalClass:
            return not (b7 or b6)
        elif trait == TlvParser.TagTrait.ApplicationClass:
            return b6
        elif trait == TlvParser.TagTrait.ContextSpecificClass:
            return b7
        elif trait == TlvParser.TagTrait.PrivateClass:
            return b7 and b6
        elif trait == TlvParser.TagTrait.PrimitiveDataObject:
            return not TlvParser.is_bit_set(upper, 5)
        elif trait == TlvParser.TagTrait.ConstructedDataObject:
            return TlvParser.is_bit_set(upper, 5)

        logging.warning(f'TlvParser trait: {trait} not supported!')
        return False

    @staticmethod
    def parse(data):
        offset = 0
        data_len = len(data)
        objects = []

        while offset < data_len:
            tag, offset = TlvParser.calculate_tlv_tag(data, offset)
            length = TlvParser.calculate_tlv_length(data, offset)

            tlv_data = data[offset:offset+length]
            offset += length
            children = []
            if TlvParser.has_trait(tag, TlvParser.TagTrait.ConstructedDataObject):
                children = TlvParser.parse(tlv_data)

            objects.append({
                'tag': tag,
                'length': length,
                'data': tlv_data,
                'children': children
            })

        return objects
