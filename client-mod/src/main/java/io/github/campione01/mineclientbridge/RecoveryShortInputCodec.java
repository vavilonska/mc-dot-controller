package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import com.google.gson.stream.*;
import java.io.*;
import java.math.BigDecimal;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Set;

/** The dedicated production wire codec: duplicate rejection and explicit null preservation. */
final class RecoveryShortInputCodec {
    private static final Gson GSON=new GsonBuilder().serializeNulls().disableHtmlEscaping().create();
    static byte[] encode(JsonObject value){return GSON.toJson(value).getBytes(StandardCharsets.UTF_8);}
    static JsonObject parse(byte[] bytes){
        if(bytes.length>8192)throw new IllegalArgumentException("body_too_large");
        JsonObject result=new JsonObject();
        try(JsonReader r=new JsonReader(new StringReader(new String(bytes,StandardCharsets.UTF_8)))){
            r.setLenient(false);r.beginObject();
            while(r.hasNext()){
                String key=r.nextName();if(result.has(key))throw new IllegalArgumentException("duplicate_json_key");
                switch(r.peek()){
                    case STRING->result.addProperty(key,r.nextString());
                    case NUMBER->result.addProperty(key,new BigDecimal(r.nextString()));
                    case BOOLEAN->result.addProperty(key,r.nextBoolean());
                    default->throw new IllegalArgumentException("flat_primitive_json_required");
                }
            }
            r.endObject();if(r.peek()!=JsonToken.END_DOCUMENT)throw new IllegalArgumentException("trailing_json");return result;
        }catch(IOException|IllegalStateException e){throw new IllegalArgumentException("invalid_json",e);}
    }
    static JsonObject statusQuery(String raw){
        if(raw==null||raw.length()>1024)throw new IllegalArgumentException("invalid_query");
        JsonObject out=new JsonObject();Set<String> keys=Set.of("id","session","owner_id","owner_generation");
        for(String part:raw.split("&",-1)){
            String[] p=part.split("=",2);if(p.length!=2)throw new IllegalArgumentException("invalid_query");
            String k=URLDecoder.decode(p[0],StandardCharsets.UTF_8),v=URLDecoder.decode(p[1],StandardCharsets.UTF_8);
            if(!keys.contains(k)||out.has(k))throw new IllegalArgumentException("invalid_query");
            if(k.equals("owner_generation")){if(!v.matches("[1-9][0-9]{0,15}"))throw new IllegalArgumentException("invalid_query");out.addProperty(k,new BigDecimal(v));}
            else out.addProperty(k,v);
        }
        if(!out.keySet().equals(keys))throw new IllegalArgumentException("invalid_query");return out;
    }
    private RecoveryShortInputCodec(){}
}
