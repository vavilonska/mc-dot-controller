package io.github.campione01.mineclientbridge;
/** Class admission happens before invoking an instance reader, including during initial capture. */
final class TypedPortalReaderPolicy {
    static <T> T exact(T value,Class<?> expected){
        if(value==null||value.getClass()!=expected)throw new IllegalStateException("typed_portal_exact_reader_required:"+expected.getName());
        return value;
    }
    private TypedPortalReaderPolicy(){}
}
