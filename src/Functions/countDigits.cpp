#include <Functions/IFunction.h>
#include <Functions/FunctionFactory.h>
#include <Functions/FunctionHelpers.h>
#include <DataTypes/DataTypesNumber.h>
#include <DataTypes/DataTypesDecimal.h>
#include <Columns/ColumnsNumber.h>
#include <Columns/ColumnDecimal.h>


namespace DB
{

namespace ErrorCodes
{
    extern const int ILLEGAL_TYPE_OF_ARGUMENT;
    extern const int ILLEGAL_COLUMN;
}

namespace
{

/// Returns number of decimal digits you need to represent the value.
/// For Decimal values takes in account their scales: calculates result over underlying int type which is (value * scale).
/// countDigits(42) = 2, countDigits(42.000) = 5, countDigits(0.04200) = 4.
/// I.e. you may check decimal overflow for Decimal64 with 'countDecimal(x) > 18'. It's a slow variant of isDecimalOverflow().
class FunctionCountDigits : public IFunction
{
public:
    static constexpr auto name = "countDigits";

    static FunctionPtr create(ContextPtr)
    {
        return std::make_shared<FunctionCountDigits>();
    }

    String getName() const override { return name; }
    bool useDefaultImplementationForConstants() const override { return true; }
    size_t getNumberOfArguments() const override { return 1; }
    bool isSuitableForShortCircuitArgumentsExecution(const DataTypesWithConstInfo & /*arguments*/) const override { return false; }

    DataTypePtr getReturnTypeImpl(const DataTypes & arguments) const override
    {
        WhichDataType which_first(arguments[0]->getTypeId());

        if (!which_first.isInt() && !which_first.isUInt() && !which_first.isDecimal())
            throw Exception(ErrorCodes::ILLEGAL_TYPE_OF_ARGUMENT, "Illegal type {} of argument of function {}",
                            arguments[0]->getName(), getName());

        return std::make_shared<DataTypeUInt8>(); /// Up to 255 decimal digits.
    }

    ColumnPtr executeImpl(const ColumnsWithTypeAndName & arguments, const DataTypePtr &, size_t input_rows_count) const override
    {
        const auto & src_column = arguments[0];
        if (!src_column.column)
            throw Exception(ErrorCodes::ILLEGAL_TYPE_OF_ARGUMENT, "Illegal column while execute function {}", getName());

        auto result_column = ColumnUInt8::create();

        auto call = [&](const auto & types) -> bool
        {
            using Types = std::decay_t<decltype(types)>;
            using Type = typename Types::RightType;
            using ColVecType = ColumnVectorOrDecimal<Type>;

            if (const ColVecType * col_vec = checkAndGetColumn<ColVecType>(src_column.column.get()))
            {
                execute<Type>(*col_vec, *result_column, input_rows_count);
                return true;
            }

            throw Exception(ErrorCodes::ILLEGAL_TYPE_OF_ARGUMENT, "Illegal column while execute function {}", getName());
        };

        TypeIndex dec_type_idx = src_column.type->getTypeId();
        if (!callOnBasicType<void, true, false, true, false>(dec_type_idx, call))
            throw Exception(ErrorCodes::ILLEGAL_COLUMN, "Wrong call for {} with {}", getName(), src_column.type->getName());

        return result_column;
    }

private:
    template <typename T, typename ColVecType>
    static void execute(const ColVecType & col, ColumnUInt8 & result_column, size_t rows_count)
    {
        using NativeT = NativeType<T>;

        const auto & src_data = col.getData();
        auto & dst_data = result_column.getData();
        dst_data.resize(rows_count);

        for (size_t i = 0; i < rows_count; ++i)
        {
            if constexpr (is_decimal<T>)
                dst_data[i] = digits<NativeT>(src_data[i].value);
            else
                dst_data[i] = digits<NativeT>(src_data[i]);
        }
    }

    template <typename T>
    static UInt32 digits(T value)
    {
        static_assert(!is_decimal<T>);
        using DivT = std::conditional_t<is_signed_v<T>, Int32, UInt32>;

        UInt32 res = 0;
        T tmp;

        if constexpr (sizeof(T) > sizeof(Int32))
        {
            static constexpr const DivT e9 = 1000000000;

            tmp = value / e9;
            while (tmp != 0)
            {
                value = tmp;
                tmp /= e9;
                res += 9;
            }
        }

        static constexpr const DivT e3 = 1000;

        tmp = value / e3;
        while (tmp != 0)
        {
            value = tmp;
            tmp /= e3;
            res += 3;
        }

        while (value != 0)
        {
            value /= 10;
            ++res;
        }
        return res;
    }
};

}

REGISTER_FUNCTION(CountDigits)
{
    factory.registerFunction<FunctionCountDigits>();
}

}
